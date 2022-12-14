/*********************************************************************
 * Software License Agreement (BSD License)
 *
 *  Copyright (c) 2019, Bielefeld University
 *  All rights reserved.
 *
 *  Redistribution and use in source and binary forms, with or without
 *  modification, are permitted provided that the following conditions
 *  are met:
 *
 *   * Redistributions of source code must retain the above copyright
 *     notice, this list of conditions and the following disclaimer.
 *   * Redistributions in binary form must reproduce the above
 *     copyright notice, this list of conditions and the following
 *     disclaimer in the documentation and/or other materials provided
 *     with the distribution.
 *   * Neither the name of Bielefeld University nor the names of its
 *     contributors may be used to endorse or promote products derived
 *     from this software without specific prior written permission.
 *
 *  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 *  "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 *  LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
 *  FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
 *  COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
 *  INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
 *  BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
 *  LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
 *  CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
 *  LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
 *  ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 *  POSSIBILITY OF SUCH DAMAGE.
 *********************************************************************/

/* Authors: Robert Haschke, Artur Istvan Karoly */

#include <generate_handover_pose.h>
#include <moveit/planning_scene/planning_scene.h>
#include <moveit/robot_state/attached_body.h>
#include <moveit/robot_state/robot_state.h>
#include <moveit/task_constructor/marker_tools.h>
#include <moveit/task_constructor/storage.h>
#include <rviz_marker_tools/marker_creation.h>

#include <Eigen/Geometry>
#include <eigen_conversions/eigen_msg.h>

namespace moveit {
namespace task_constructor {
namespace stages {

GenerateHandoverPose::GenerateHandoverPose(const std::string &name)
    : GeneratePose(name) {
  auto &p = properties();
  p.declare<std::string>("object");
  p.declare<geometry_msgs::PoseStamped>("ik_frame");
}

void GenerateHandoverPose::onNewSolution(const SolutionBase &s) {
  planning_scene::PlanningSceneConstPtr scene = s.end()->scene();

  const auto &props = properties();
  const std::string &object = props.get<std::string>("object");
  std::string msg;
  if (!scene->getCurrentState().hasAttachedBody(object))
    msg = "'" + object + "' is not an attached object";
  if (scene->getCurrentState()
          .getAttachedBody(object)
          ->getFixedTransforms()
          .empty())
    msg = "'" + object + "' has no associated shapes";
  if (!msg.empty()) {
    if (storeFailures()) {
      InterfaceState state(scene);
      SubTrajectory solution;
      solution.markAsFailure();
      solution.setComment(msg);
      spawn(std::move(state), std::move(solution));
    } else
      ROS_WARN_STREAM_NAMED("GenerateHandoverPose", msg);
    return;
  }

  upstream_solutions_.push(&s);
}

void GenerateHandoverPose::compute() {
  if (upstream_solutions_.empty())
    return;

  const SolutionBase &s = *upstream_solutions_.pop();
  planning_scene::PlanningSceneConstPtr scene = s.end()->scene()->diff();
  const moveit::core::RobotState &robot_state = scene->getCurrentState();
  const auto &props = properties();

  const moveit::core::AttachedBody *object =
      robot_state.getAttachedBody(props.get<std::string>("object"));
  // current object_pose w.r.t. planning frame
  const Eigen::Isometry3d &orig_object_pose =
      object->getGlobalCollisionBodyTransforms()[0];

  const geometry_msgs::PoseStamped &pose_msg =
      props.get<geometry_msgs::PoseStamped>("pose");
  Eigen::Isometry3d target_pose;
  tf::poseMsgToEigen(pose_msg.pose, target_pose);
  // target pose w.r.t. planning frame
  scene->getTransforms().transformPose(pose_msg.header.frame_id, target_pose,
                                       target_pose);

  const geometry_msgs::PoseStamped &ik_frame_msg =
      props.get<geometry_msgs::PoseStamped>("ik_frame");
  Eigen::Isometry3d ik_frame;
  tf::poseMsgToEigen(ik_frame_msg.pose, ik_frame);
  ik_frame = robot_state.getGlobalLinkTransform(ik_frame_msg.header.frame_id) *
             ik_frame;

  Eigen::Isometry3d object_to_ik;
  object_to_ik = orig_object_pose.inverse() * ik_frame;

  geometry_msgs::PoseStamped target_pose_msg;
  target_pose_msg.header.frame_id = scene->getPlanningFrame();

  // Spawn 16 poses (rotate along x first -> rotate along z second -> 4 x 4 = 16
  // poses)
  for (uint flip = 0; flip < 4; ++flip) {
    Eigen::Isometry3d flipped =
        target_pose *
        Eigen::AngleAxisd(flip * M_PI / 2, Eigen::Vector3d::UnitX());
    for (uint rotate = 0; rotate < 4; ++rotate) {
      Eigen::Isometry3d rotated =
          flipped *
          Eigen::AngleAxisd(rotate * M_PI / 2, Eigen::Vector3d::UnitZ());
      tf::poseEigenToMsg(rotated * object_to_ik, target_pose_msg.pose);

      InterfaceState state(scene);
      forwardProperties(*s.end(),
                        state); // forward properties from inner solutions
      state.properties().set("target_pose", target_pose_msg);

      SubTrajectory trajectory;
      trajectory.setCost(0.0);
      rviz_marker_tools::appendFrame(trajectory.markers(), target_pose_msg, 0.1,
                                     "handover frame");

      spawn(std::move(state), std::move(trajectory));
    }
  }

  // Spawn the 8 remaining poses (rotate along y first - rotate along z second,
  // but the rotatins around y by 0 and 90 degrees have already been added above
  // -> 2 x 4 = 8 poses)
  for (uint flip = 0; flip < 2; ++flip) {
    Eigen::Isometry3d flipped =
        target_pose *
        Eigen::AngleAxisd((2 * flip + 1) * M_PI / 2, Eigen::Vector3d::UnitY());
    for (uint rotate = 0; rotate < 4; ++rotate) {
      Eigen::Isometry3d rotated =
          flipped *
          Eigen::AngleAxisd(rotate * M_PI / 2, Eigen::Vector3d::UnitZ());
      tf::poseEigenToMsg(rotated * object_to_ik, target_pose_msg.pose);

      InterfaceState state(scene);
      forwardProperties(*s.end(),
                        state); // forward properties from inner solutions
      state.properties().set("target_pose", target_pose_msg);

      SubTrajectory trajectory;
      trajectory.setCost(0.0);
      rviz_marker_tools::appendFrame(trajectory.markers(), target_pose_msg, 0.1,
                                     "handover frame");

      spawn(std::move(state), std::move(trajectory));
    }
  }
}
} // namespace stages
} // namespace task_constructor
} // namespace moveit
