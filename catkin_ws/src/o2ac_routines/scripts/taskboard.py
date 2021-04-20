#!/usr/bin/env python

# Software License Agreement (BSD License)
#
# Copyright (c) 2020, Team O2AC
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above
#    copyright notice, this list of conditions and the following
#    disclaimer in the documentation and/or other materials provided
#    with the distribution.
#  * Neither the name of Team O2AC nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#
# Author: Felix von Drigalski

import sys
import copy
import rospy
import geometry_msgs.msg
import tf_conversions
import tf
import math
from math import pi, degrees, radians, sin, cos
tau = 2.0*pi  # Part of math from Python 3.6
import math
import traceback
import time

from o2ac_msgs.srv import *
import actionlib
import o2ac_msgs.msg

import o2ac_msgs
import o2ac_msgs.srv

# import o2ac_assembly_database
from o2ac_assembly_database.parts_reader import PartsReader

from o2ac_routines.common import O2ACCommon
from o2ac_routines.helpers import wait_for_UR_program

class TaskboardClass(O2ACCommon):
  """
  This contains the routines used to run the taskboard task.
  """
  def __init__(self):
    super(TaskboardClass, self).__init__()
    
    # self.action_client.wait_for_server()
    rospy.sleep(.5)   # Use this instead of waiting, so that simulation can be used

    # Initialize debug monitor
    self.start_task_timer()
    
    self.downward_orientation = geometry_msgs.msg.Quaternion(*tf_conversions.transformations.quaternion_from_euler(0, tau/4, pi))
    self.downward_orientation_cylinder_axis_along_workspace_x = geometry_msgs.msg.Quaternion(*tf_conversions.transformations.quaternion_from_euler(0, tau/4, tau/4))

    self.at_set_screw_hole = geometry_msgs.msg.PoseStamped()
    self.at_set_screw_hole.header.frame_id = "taskboard_set_screw_link"
    self.at_set_screw_hole.pose.orientation = geometry_msgs.msg.Quaternion(*tf_conversions.transformations.quaternion_from_euler(0, 0, 0))
    self.at_set_screw_hole.pose.position.x = 0.001   # MAGIC NUMBER
    self.at_set_screw_hole.pose.position.y = -0.0005   # MAGIC NUMBER
    self.at_set_screw_hole.pose.position.z = 0.001   # MAGIC NUMBER (points downward)
    if not self.assembly_database.db_name == "taskboard":
      self.assembly_database.change_assembly("taskboard")

  def multiply_quaternion_msgs(self, q1_msg, q2_msg):
    q1 = [q1_msg.x, q1_msg.y, q1_msg.z, q1_msg.w]
    q2 = [q2_msg.x, q2_msg.y, q2_msg.z, q2_msg.w]
    return geometry_msgs.msg.Quaternion(*tf.transformations.quaternion_multiply(q1, q2))
    
  def spawn_example_objects(self):
    # This function spawns the objects into the tray as if they had been recognized by the vision node
    names = ["taskboard_idler_pulley_small", "bearing", "shaft", "motor_pulley"]
    offsets = {"bearing": [-.04, -.02, .001],
    "taskboard_idler_pulley_small": [.07, .06, .03], 
    "shaft": [.03, -.06, .005], 
    "motor_pulley": [-.01, .12, .005], 
    "endcap": [-.05, -.1, .005]}

    # We publish each object to its own frame.
    broadcaster = tf.TransformBroadcaster()
    rospy.sleep(.5)
    counter = 0
    for name in names:
      collision_object = self.assembly_database.get_collision_object(name)
      if collision_object:
        counter += 1
        collision_object.header.frame_id = "collision_object_spawn_helper_frame" + str(counter)
        if name == "bearing":
          q_rotate = tf_conversions.transformations.quaternion_from_euler(0, tau/4, 0)
        if name == "taskboard_idler_pulley_small" or name == "motor_pulley":
          q_rotate = tf_conversions.transformations.quaternion_from_euler(0, tau/4, 0)
        elif name == "shaft":
          q_rotate = tf_conversions.transformations.quaternion_from_euler(0, 0, 0)
          
        offset = offsets[name]
        broadcaster.sendTransform((offset[0], offset[1], offset[2]), q_rotate, rospy.Time.now(), 
            "collision_object_spawn_helper_frame" + str(counter), "tray_center")
        rospy.sleep(1.0) # Wait for the transform to have propagated through the system

        self.planning_scene_interface.add_object(collision_object)
        # print("======== collision object: " + name)
        # print(collision_object.mesh_poses)
        # print(collision_object.subframe_names)
        # print(collision_object.subframe_poses)
      else:
        rospy.logerr("Could not retrieve collision object:" + name)

  #####
  
  def allow_collision_with_hand(self, robot_name, object_name):
    self.planning_scene_interface.allow_collisions(object_name, robot_name + "_robotiq_85_tip_link")
    self.planning_scene_interface.allow_collisions(object_name, robot_name + "_robotiq_85_left_finger_tip_link")
    self.planning_scene_interface.allow_collisions(object_name, robot_name + "_robotiq_85_left_inner_knuckle_link")
    self.planning_scene_interface.allow_collisions(object_name, robot_name + "_robotiq_85_right_finger_tip_link")
    self.planning_scene_interface.allow_collisions(object_name, robot_name + "_robotiq_85_right_inner_knuckle_link")

  def disallow_collision_with_hand(self, robot_name, object_name):
    self.planning_scene_interface.disallow_collisions(object_name, robot_name + "_robotiq_85_tip_link")
    self.planning_scene_interface.disallow_collisions(object_name, robot_name + "_robotiq_85_left_finger_tip_link")
    self.planning_scene_interface.disallow_collisions(object_name, robot_name + "_robotiq_85_left_inner_knuckle_link")
    self.planning_scene_interface.disallow_collisions(object_name, robot_name + "_robotiq_85_right_finger_tip_link")
    self.planning_scene_interface.disallow_collisions(object_name, robot_name + "_robotiq_85_right_inner_knuckle_link")

  def look_in_tray(self):
    #TODO (felixvd)
    # Look at tray
    # loop through all items
    # check if they were recognized and are graspable
    # otherwise check position again
    # if still not graspable either skip to next item or try to reposition
    pass
  
  def prep_taskboard_task(self):
    """
    Equip the set screw tool and M3 tool, and move to the position before task start.
    """

    self.go_to_named_pose("home", "a_bot")

    self.do_change_tool_action("a_bot", equip=True, screw_size = 3)
    self.go_to_named_pose("feeder_pick_ready", "a_bot")

    self.go_to_named_pose("home", "b_bot")
    
    self.do_change_tool_action("b_bot", equip=True, screw_size = 2)  # Set screw tool
    self.go_to_named_pose("horizontal_screw_ready", "b_bot")

    self.move_b_bot_to_setscrew_initial_pos()
  
  def move_b_bot_to_setscrew_initial_pos(self):
    screw_approach = copy.deepcopy(self.at_set_screw_hole)
    screw_approach.pose.position.x = -0.005
    self.go_to_pose_goal("b_bot", screw_approach, end_effector_link="b_bot_set_screw_tool_tip_link", move_lin=True, speed=0.5)

  def align_bearing_holes(self, max_adjustments=15):
    """
    Hacky solution to align the bearing holes.
    """
    self.activate_camera("b_bot_inside_camera")
    self.activate_led("b_bot", on=False)
    adjustment_motions = 0
    times_looked_without_action = 0
    times_it_looked_like_success = 0
    
    success = False
    while adjustment_motions < max_adjustments:
      # Look at tb bearing
      ps = geometry_msgs.msg.PoseStamped()
      ps.header.frame_id = "taskboard_bearing_target_link"
      ps.pose.orientation = geometry_msgs.msg.Quaternion(*(0.5, 0.5, 0.5, 0.5))
      ps.pose.position = geometry_msgs.msg.Point(-0.155, -0.005, -0.0)
      self.go_to_pose_goal("b_bot", ps, end_effector_link="b_bot_inside_camera_color_optical_frame", speed=.1, acceleration=.04)
      self.activate_led("b_bot", on=True)
      self.open_gripper("b_bot")
      rospy.sleep(1)  # Without a wait, the camera image is blurry

      # Get angle and turn
      angle = self.get_bearing_angle()
      self.activate_led("b_bot", on=False)
      if angle:
        rospy.loginfo("Bearing detected angle: %3f", degrees(angle))
        # rospy.loginfo(str(degrees(angle)))
        b_bot_at_tb_bearing = [1.56031179, -1.25635559, 1.8379710, -2.2435614, -2.6155634, -1.55478078]
        if abs(degrees(angle)) > 3.5: # One execution = 5 degrees roughly
          self.open_gripper("b_bot")
          self.move_joints("b_bot", b_bot_at_tb_bearing)
          if degrees(angle) < 3.5:
            success = self.load_program(robot="b_bot", program_name="wrs2020/taskboard_bearing_turn_left.urp", recursion_depth=3)
            rospy.loginfo("executing bearing left turn")
          elif degrees(angle) > 3.5:
            success = self.load_program(robot="b_bot", program_name="wrs2020/taskboard_bearing_turn_right.urp", recursion_depth=3)  
            rospy.loginfo("executing bearing right turn")
          if success:
            turns_to_do = max( round((abs(degrees(angle))/6.0)), 1)
            for i in range(int(turns_to_do)):
              self.execute_loaded_program(robot="b_bot")
              wait_for_UR_program("/b_bot", rospy.Duration.from_sec(15))
            adjustment_motions += 1
            times_looked_without_action = 0
            times_it_looked_like_success = 0
          self.activate_ros_control_on_ur("b_bot")
        else:
          rospy.loginfo("Bearing angle < 5 deg, not executing a motion")
          times_looked_without_action += 1
          times_it_looked_like_success += 1
      else:
        rospy.logwarn("Bearing angle not found in image.")
        times_looked_without_action += 1
      if times_looked_without_action > 3:
        if times_it_looked_like_success > 2:
          rospy.loginfo("Bearing angle looked correct " + str(times_it_looked_like_success) + " out of the last " + str(times_looked_without_action) + " times. Judged successful.")
          return True
        rospy.logerr("Bearing perception failed too often. Breaking out")
        return False
    rospy.logerr("Did not manage to align the bearing holes.")
    return False

  def do_screw_tasks_from_prep_position(self):
    ### - Set screw
    
    # Move into the screw hole with motor on
    self.activate_camera("b_bot_inside_camera")
    self.do_task("M2 set screw")
    
    # TODO: check set screw success with a_bot, do spiral motion with b_bot otherwise
    
    ### SCREW M3 WITH A_BOT
    # self.activate_camera("a_bot_outside_camera")
    self.pick_screw_from_feeder("a_bot", screw_size = 3)
    self.go_to_named_pose("home", "a_bot")

    # Move b_bot back, a_bot to screw
    self.do_change_tool_action("b_bot", equip=False, screw_size = 2)
    self.do_change_tool_action("b_bot", equip=True, screw_size = 4)
    self.go_to_named_pose("home", "b_bot")

    self.do_task("M3 screw")
    
    ###
    
    #### SCREW M4 WITH B_BOT
    self.do_task("M4 screw")

    self.do_change_tool_action("a_bot", equip=False, screw_size = 3)
    self.go_to_named_pose("home", "a_bot")
    self.go_to_named_pose("home", "b_bot")
    self.do_change_tool_action("b_bot", equip=False, screw_size = 4)

  def full_taskboard_task(self, do_screws=True):
    """
    Start the taskboard task from the fully prepped position (set screw tool and M3 tool equipped)
    """
    #####
    if do_screws:
      self.do_screw_tasks_from_prep_position()

    subtask_completed = {
      "M2 set screw": True,
      "M3 screw": True,
      "M4 screw": True,
      "belt": False,
      "bearing": False,
      "motor pulley": False,
      "shaft": False,
      "idler pulley": True,
    }

    ### - Belt
    subtask_completed["belt"] = self.do_task("belt")
    
    # # - Retainer pin + nut
    # subtask_completed["idler pulley"] = self.do_task("idler pulley")
    # self.do_change_tool_action("b_bot", equip=False, screw_size = 4)

    # - Shaft
    subtask_completed["shaft"] = self.do_task("shaft")
    
    # - Motor pulley
    subtask_completed["motor pulley"] = self.do_task("motor pulley")

    # TODO: 
    # Implement bearing regrasp
    subtask_completed["bearing"] = self.do_task("bearing")
    if subtask_completed["bearing"]:
      subtask_completed["screw_bearing"] = self.do_task("screw_bearing")

    self.confirm_to_proceed("Continue into loop to retry parts?")
    order = ["shaft", "motor pulley", "belt", "bearing"]
    task_complete = False
    while not task_complete and not rospy.is_shutdown():
      for item in order:
        if not subtask_completed[item]:
          self.confirm_to_proceed("Reattempt " + str(item) + "?")
          subtask_completed[item] = self.do_task(item)
          if item == "bearing" and subtask_completed[item]: 
            if not subtask_completed["screw_bearing"]:
              self.do_task("screw_bearing")
      

  def do_task(self, task_name):
    
    if task_name == "belt":
      # - Equip the belt tool with b_bot
      # self.equip_tool("belt_tool")
      
      self.go_to_named_pose("home","a_bot")
      
      self.go_to_pose_goal("b_bot", self.tray_view_high, end_effector_link="b_bot_outside_camera_color_frame", speed=.3, acceleration=.1)

      self.activate_camera("b_bot_outside_camera")
      self.activate_led("b_bot")
      res = self.get_3d_poses_from_ssd()
      r2 = self.get_feasible_grasp_points("belt")
      if r2:
        goal = r2[0]
        goal.pose.position.z = 0.0
      else:
        rospy.logerr("Could not find belt grasp pose! Aborting.")
        return False
      
      # Start the program with b_bot to pick the tool
      self.go_to_named_pose("home","b_bot")
      success_b = self.load_program(robot="b_bot", program_name="wrs2020/taskboard_belt_v4.urp", recursion_depth=3)
      if success_b:
        print("Running belt pick on b_bot.")
        if not self.execute_loaded_program(robot="b_bot"):
          rospy.logerr("Failed to execute belt picking program on b_bot")
      else:
        return False
      
      self.simple_pick("a_bot", goal, gripper_force=100.0, grasp_width=.05, axis="z")
      a_bot_wait_with_belt_pose = [0.646294116973877, -1.602117200891012, 2.0059760252581995, -1.3332312864116211, -0.8101084868060511, -2.4642069975482386]
      self.move_joints("a_bot", a_bot_wait_with_belt_pose)

      # TODO: Check for pick success with cameras
      
      success_a = self.load_program(robot="a_bot", program_name="wrs2020/taskboard_belt_v5.urp", recursion_depth=3)      
      if success_a and success_b:
        print("Loaded belt program on a_bot.")
        rospy.sleep(1)
        success = self.execute_loaded_program(robot="a_bot")
        if success:
          print("Starting belt threading execution.")
          rospy.sleep(2)
          self.close_ur_popup(robot="a_bot")
          self.close_ur_popup(robot="b_bot")
      else:
        print("Problem loading. Not executing belt procedure.")
      wait_for_UR_program("/b_bot", rospy.Duration.from_sec(20))
      return True
      

    # ==========================================================

    if task_name == "M2 set screw":
      # Equip and move to the screw hole
      # self.do_change_tool_action("b_bot", equip=True, screw_size = 2)  # Set screw tool
      # self.go_to_named_pose("horizontal_screw_ready", "b_bot")
      screw_approach = copy.deepcopy(self.at_set_screw_hole)
      screw_approach.pose.position.x = -0.005
      self.go_to_pose_goal("b_bot", screw_approach, end_effector_link="b_bot_set_screw_tool_tip_link", move_lin=True)
      self.go_to_pose_goal("b_bot", self.at_set_screw_hole, end_effector_link="b_bot_set_screw_tool_tip_link", move_lin=True, speed=0.02)

      # This expects to be exactly above the set screw hole
      self.confirm_to_proceed("Turn on motor and move into screw hole?")
      dist = .002
      self.move_lin_rel("b_bot", relative_translation=[0, -cos(radians(30))*dist, sin(radians(30))*dist], velocity=0.03, wait=False)
      # self.horizontal_spiral_motion("b_bot", .003, spiral_axis="Y", radius_increment = .002)
      self.set_motor("set_screw_tool", "tighten", duration = 12.0)
      rospy.sleep(4.0) # Wait for the screw to be screwed in a little bit
      d = .004
      rospy.loginfo("Moving in further by " + str(d) + " m.")
      self.move_lin_rel("b_bot", relative_translation=[0, -cos(radians(30))*d, sin(radians(30))*d], velocity=0.002, wait=False)
      
      # self.do_linear_push("b_bot", force=40, direction_vector=[0, -cos(radians(30)), sin(radians(30))], forward_speed=0.001)
      rospy.sleep(8.0)
      self.confirm_to_proceed("Go back?")
      if self.is_robot_protective_stopped("b_bot"):
        rospy.logwarn("Robot was protective stopped after set screw insertion!")
        #TODO: Recovery? Try to loosen the shaft?
        self.unlock_protective_stop("b_bot")
        rospy.sleep(1)
        if self.is_robot_protective_stopped("b_bot"):
          return False

      # Go back
      self.go_to_pose_goal("b_bot", screw_approach, end_effector_link="b_bot_set_screw_tool_tip_link", move_lin=True)

      self.go_to_named_pose("horizontal_screw_ready", "b_bot", speed=0.5, acceleration=0.5)
      # self.confirm_to_proceed("Unequip tool?")
      # self.go_to_named_pose("home", "b_bot", speed=0.5, acceleration=0.5)
      # self.do_change_tool_action("b_bot", equip=False, screw_size = 2)  # Set screw tool
    
    # ==========================================================

    if task_name == "M3 screw":
      self.go_to_named_pose("horizontal_screw_ready", "a_bot")
      approach_pose = geometry_msgs.msg.PoseStamped()
      approach_pose.header.frame_id = "taskboard_m3_screw_link"
      approach_pose.pose.position.x = -.04
      approach_pose.pose.position.y = -.12
      approach_pose.pose.position.z = -.05
      taskboard.go_to_pose_goal("a_bot", approach_pose, speed=0.5, end_effector_link="a_bot_screw_tool_m3_tip_link", move_lin = True)

      approach_pose.pose.position.y = -.0
      approach_pose.pose.position.z = -.0
      taskboard.go_to_pose_goal("a_bot", approach_pose, speed=0.5, end_effector_link="a_bot_screw_tool_m3_tip_link", move_lin = True)

      hole_pose = geometry_msgs.msg.PoseStamped()
      hole_pose.header.frame_id = "taskboard_m3_screw_link"
      hole_pose.pose.position.y = -.000  # MAGIC NUMBER (this should offset towards a_bot (z-axis of the frame points down))
      hole_pose.pose.position.z = -.004  # MAGIC NUMBER (this should offset upwards (z-axis of the frame points down))
      hole_pose.pose.orientation = geometry_msgs.msg.Quaternion(*tf_conversions.transformations.quaternion_from_euler(-tau/12, 0, 0))
      taskboard.do_screw_action("a_bot", hole_pose, screw_size = 3)
      self.go_to_named_pose("horizontal_screw_ready", "a_bot")
      self.go_to_named_pose("home", "a_bot")

    # ==========================================================

    if task_name == "M4 screw":
      self.activate_camera("b_bot_outside_camera")
      self.pick_screw_from_feeder("b_bot", screw_size = 4)
      self.go_to_named_pose("horizontal_screw_ready", "b_bot")
      hole_pose = geometry_msgs.msg.PoseStamped()
      hole_pose.header.frame_id = "taskboard_m4_screw_link"
      hole_pose.pose.orientation = geometry_msgs.msg.Quaternion(*tf_conversions.transformations.quaternion_from_euler(tau/12, 0, 0))
      hole_pose.pose.position.y = -.001  # MAGIC NUMBER (this should offset towards a_bot (z-axis of the frame points down))
      hole_pose.pose.position.z = -.001  # MAGIC NUMBER (this should offset upwards (z-axis of the frame points down))
      self.do_screw_action("b_bot", hole_pose, screw_size = 4)
      self.go_to_named_pose("horizontal_screw_ready", "b_bot")
      self.go_to_named_pose("home", "b_bot")

    # ==========================================================

    if task_name == "motor pulley":
      self.go_to_named_pose("home","a_bot")
      self.go_to_named_pose("home","b_bot")
      
      goal = self.look_and_get_grasp_point(self.assembly_database.name_to_id("motor_pulley"))
      if not goal:
        rospy.logerr("Could not find motor_pulley in tray. Skipping procedure.")
        return False
      goal.pose.position.x -= 0.01 # MAGIC NUMBER
      goal.pose.position.z = 0.0
      self.activate_camera("b_bot_inside_camera")
      self.activate_led("b_bot")
      self.simple_pick("b_bot", goal, gripper_force=50.0, grasp_width=.06, axis="z")
      if self.b_bot_gripper_opening_width < 0.01:
        rospy.logerr("Gripper did not grasp the pulley --> Stop")

      b_bot_script_start_pose = [1.7094888, -1.76184906, 2.20651847, -2.03368343, -1.54728252, 0.96213197]
      self.move_joints("b_bot", b_bot_script_start_pose)
      success_b = self.load_program(robot="b_bot", program_name="wrs2020/pulley_v3.urp", recursion_depth=3)
      if success_b:
        print("Loaded pulley program.")
        rospy.sleep(1)
        self.execute_loaded_program(robot="b_bot")
        print("Started execution. Waiting for b_bot to finish.")
      else:
        print("Problem loading. Not executing pulley procedure.")
        return False
      wait_for_UR_program("/b_bot", rospy.Duration.from_sec(40))
      return True

      # # pick up pulley
      # self.allow_collision_with_hand('b_bot', 'motor_pulley')
      # pick_pose = geometry_msgs.msg.PoseStamped()
      # pick_pose.header.frame_id = "move_group/motor_pulley"
      # pick_pose.pose.position = geometry_msgs.msg.Point(-0.02, 0, 0)
      # pick_pose.pose.orientation = geometry_msgs.msg.Quaternion(*tf_conversions.transformations.quaternion_from_euler(0, 0, tau/2))
      # tool_name = "motor_pulley"
      # robot_name = "b_bot"
      # self.simple_pick("b_bot", pick_pose, item_id_to_attach="motor_pulley")
      # # insert pulley
      # self.allow_collision_with_hand('b_bot', 'taskboard_base')
      # insert_pose = geometry_msgs.msg.PoseStamped()
      # insert_pose.header.frame_id = "taskboard_small_shaft"
      # insert_pose.pose.position = geometry_msgs.msg.Point(0.025, 0, 0)
      # insert_pose.pose.orientation = geometry_msgs.msg.Quaternion(*tf_conversions.transformations.quaternion_from_euler(tau/4, tau/2, tau/2))
      # self.simple_place("b_bot", insert_pose, item_id_to_detach="motor_pulley")
      # self.disallow_collision_with_hand('b_bot', 'taskboard_base')
      # self.disallow_collision_with_hand('b_bot', 'motor_pulley')
      # self.planning_scene_interface.allow_collisions('motor_pulley', 'taskboard_small_shaft')
      # self.planning_scene_interface.allow_collisions('motor_pulley', 'taskboard_base')
      # self.planning_scene_interface.allow_collisions('taskboard_base', 'taskboard_plate')
      # # Go back to home position
      # self.go_to_named_pose("home","b_bot")
    
    # ==========================================================

    if task_name == "bearing":
      self.go_to_named_pose("home","a_bot")
      self.go_to_named_pose("home","b_bot")

      goal = self.look_and_get_grasp_point("bearing")
      if not goal:
        rospy.logerr("Could not find bearing in tray. Skipping procedure.")
        return False
      self.activate_camera("b_bot_inside_camera")
      goal.pose.position.x -= 0.01 # MAGIC NUMBER
      goal.pose.position.z = 0.0115
      self.simple_pick("b_bot", goal, gripper_force=100.0, approach_height=0.05, axis="z")

      if self.b_bot_gripper_opening_width < 0.045:
        rospy.loginfo("bearing found to be upwards")
        success_b = self.load_program(robot="b_bot", program_name="wrs2020/bearing_orient_totb.urp", recursion_depth=3)
      else:
        rospy.loginfo("bearing found to be upside down")
        success_b = self.load_program(robot="b_bot", program_name="wrs2020/bearing_orient_down_totb.urp", recursion_depth=3)
        #'down' means the small area contacts with tray.
      
      if success_b:
        print("Loaded bearing orient program.")
        self.execute_loaded_program(robot="b_bot")
        print("Started execution. Waiting for b_bot to finish.")
      else:
        print("Problem loading. Not executing bearing orient procedure.")
        return False
      wait_for_UR_program("/b_bot", rospy.Duration.from_sec(70))

      if self.b_bot_gripper_opening_width < 0.01:
        rospy.logerr("Bearing not found in gripper. Must have been lost. Aborting.")
        #TODO(felixvd): Look at the regrasping/aligning area next to the tray
        return False

      #Insert bearing
      insert = self.load_program(robot="b_bot", program_name="wrs2020/bearing_insert.urp", recursion_depth=3)
      if insert:
        print("Loaded bearing insert program.")
        self.execute_loaded_program(robot="b_bot")
        print("Started execution. Waiting for b_bot to finish.")
      else:
        print("Problem loading. Not executing bearing insert procedure.")
        return False
      wait_for_UR_program("/b_bot", rospy.Duration.from_sec(70))

      self.bearing_holes_aligned = self.align_bearing_holes()
      return self.bearing_holes_aligned

      ### Sequence including regrasp
      # TODO: Rewrite either with MTC or manually, so that B ends up with the bearing
      # Then rewrite like this:
      # 1. Grasp bearing with b_bot
      # 2. Place and regrasp to center it 
      # 3. Push on the taskboard with a_bot at this position:
      # 0.00063529; 0.0099509; 0.048085
      # -0.0079834; 0.71742; 0.0079052; 0.69655   (90 deg rotation around y)
      # 4. Insert with b_bot

      # Check if bearing is facing upright
      bearing_hole_pose = geometry_msgs.msg.PoseStamped()
      bearing_hole_pose.header.frame_id = "move_group/bearing/front_hole"
      bearing_hole_pose.pose.orientation.w = 1.0
      bearing_hole_pose_in_world = self.listener.transformPose("workspace_center", bearing_hole_pose)
      self.allow_collision_with_hand('b_bot', 'bearing')
      if (bearing_hole_pose_in_world.pose.position.z < 0.03): # Bearing faces upward
        rospy.loginfo("Regrasp and Insert")
        # Pick up the bearing by b_bot
        rospy.loginfo("Pick up the bearing")
        pick_pose = geometry_msgs.msg.PoseStamped()
        pick_pose.header.frame_id = "move_group/bearing"
        pick_pose.pose.position = geometry_msgs.msg.Point(-0.065, 0, 0)
        pick_pose.pose.orientation = geometry_msgs.msg.Quaternion(*tf_conversions.transformations.quaternion_from_euler(-tau/4, 0, 0))
        self.simple_pick("b_bot", pick_pose, item_id_to_attach="bearing", approach_height=-0.05, grasp_height=-0.05, sign=-1)
        # Hand over the bearing from b_bot to a_bot
        rospy.loginfo("Handover pose (B)")
        self.go_to_named_pose("bearing_handover", "a_bot")
        rospy.loginfo("Handover pose (A)")
        handover_pose = geometry_msgs.msg.PoseStamped()
        handover_pose.header.frame_id = "a_bot_robotiq_85_tip_link"
        handover_pose.pose.position = geometry_msgs.msg.Point(0.05, 0, 0)
        handover_pose.pose.orientation = geometry_msgs.msg.Quaternion(*tf_conversions.transformations.quaternion_from_euler(-tau/4, 0, tau/2))
        self.go_to_pose_goal("a_bot", handover_pose, move_lin=False)
        rospy.loginfo("Handover")
        handover_pose2 = geometry_msgs.msg.PoseStamped()
        handover_pose2.header.frame_id = "b_bot_robotiq_85_tip_link"
        handover_pose2.pose.position = geometry_msgs.msg.Point(-0.01, 0, 0)
        handover_pose2.pose.orientation = geometry_msgs.msg.Quaternion(*tf_conversions.transformations.quaternion_from_euler(-tau/4, 0, tau/2))
        self.go_to_pose_goal("a_bot", handover_pose2, move_lin=False)
        self.groups["b_bot"].detach_object("bearing")
        self.groups["a_bot"].attach_object("bearing")
        # Move hands to avoid collision
        rospy.loginfo("Retreat")
        
        self.go_to_named_pose("home","b_bot")
        # TODO: Center bearing and pick it with inclination

      else:
        # pick up bearing
        pick_pose = geometry_msgs.msg.PoseStamped()
        pick_pose.header.frame_id = "move_group/bearing"
        pick_pose.pose.position = geometry_msgs.msg.Point(-0.03, 0.0, 0.0)
        pick_pose.pose.orientation = geometry_msgs.msg.Quaternion(*tf_conversions.transformations.quaternion_from_euler(tau/4, 0, tau/2))
        self.simple_pick("a_bot", pick_pose, item_id_to_attach="bearing")
      # insert bearing
      rospy.loginfo("Insert bearing by a_bot")
      self.allow_collision_with_hand('b_bot', 'taskboard_plate')
      self.allow_collision_with_hand('b_bot', 'taskboard_bearing_target_link')
      insert_pose = geometry_msgs.msg.PoseStamped()
      insert_pose.header.frame_id = "taskboard_bearing_target_link"
      insert_pose.pose.position = geometry_msgs.msg.Point(0.02, 0.0, 0.0)
      insert_pose.pose.orientation = geometry_msgs.msg.Quaternion(*tf_conversions.transformations.quaternion_from_euler(tau/4, 0, 0))
      self.simple_place("a_bot", insert_pose, item_id_to_detach="bearing")
      self.disallow_collision_with_hand('b_bot', 'bearing')
      self.disallow_collision_with_hand('b_bot', 'taskboard_bearing_target_link')
      # self.planning_scene_interface.allow_collisions('taskboard_base', 'taskboard_plate')
      self.planning_scene_interface.allow_collisions('bearing', 'taskboard_plate')
      self.go_to_named_pose("home","a_bot")

    if task_name == "screw_bearing":  # Just an intermediate for debugging.
      self.go_to_named_pose("home", "a_bot")
      self.equip_tool('b_bot', 'screw_tool_m4')
      intermediate_pose = [31.0 /180.0*3.14, -137.0 /180.0*3.14, 121.0 /180.0*3.14, -114.0 /180.0*3.14, -45.0 /180.0*3.14, -222.0 /180.0*3.14]
      
      success_a = self.load_program(robot="a_bot", program_name="wrs2020/linear_push_on_taskboard_from_home.urp", recursion_depth=3)
      
      if success_a:
        print("Loaded push_on_taskboard.")
        rospy.sleep(1)
        self.execute_loaded_program(robot="a_bot")
        print("Started execution. Pushing on taskboard.")
      else:
        print("Problem loading. Not executing push on taskboard.")
        # self.unequip_tool('b_bot', 'screw_tool_m4')
        self.do_change_tool_action("b_bot", equip=False, screw_size = 4)
        return

      for n in [1,3,2,4]:  # Cross pattern
        if rospy.is_shutdown():
          break
        # self.go_to_named_pose("home","b_bot")
        self.move_joints("b_bot", intermediate_pose)
        self.go_to_named_pose("feeder_pick_ready","b_bot")
        self.pick_screw_from_feeder("b_bot", screw_size=4)
        # self.go_to_named_pose("home","b_bot")
        self.move_joints("b_bot", intermediate_pose)
        self.go_to_named_pose("horizontal_screw_ready","b_bot")
        screw_pose = geometry_msgs.msg.PoseStamped()
        screw_pose.header.frame_id = "/taskboard_bearing_target_screw_" + str(n) + "_link"
        screw_pose.pose.position.z = -0.003  ## MAGIC NUMBER
        screw_pose.pose.orientation.w = 1.0
        screw_pose_approach = copy.deepcopy(screw_pose)
        screw_pose_approach.pose.position.x -= 0.05
        self.go_to_pose_goal("b_bot", screw_pose_approach, end_effector_link = "b_bot_screw_tool_m3_tip_link", move_lin=False)
        if self.use_real_robot:
          self.do_screw_action("b_bot", screw_pose, screw_size=4)
          self.go_to_pose_goal("b_bot", screw_pose_approach, end_effector_link = "b_bot_screw_tool_m3_tip_link", move_lin=False)
          self.go_to_named_pose("home","b_bot")
        else:
          time.sleep(1.0)
      self.move_joints("b_bot", intermediate_pose)
      self.go_to_named_pose("tool_pick_ready","b_bot")
      success = self.go_to_named_pose("home", "a_bot")
      while not success and not rospy.is_shutdown():
        rospy.logerr("a_bot failed to go home, but unequip is dangerous unless it is out of the way. Repeat.")
        success = self.go_to_named_pose("home", "a_bot")
        
      self.unequip_tool('b_bot', 'screw_tool_m4')
    
    # ==========================================================

    if task_name == "shaft":
      self.go_to_named_pose("home","a_bot")
      self.go_to_named_pose("home","b_bot")

      goal = self.look_and_get_grasp_point(self.assembly_database.name_to_id("shaft"))
      if not goal:
        rospy.logerr("Could not find shaft in tray. Skipping procedure.")
        print(self.objects_in_tray)
        return False
      goal.pose.position.z = 0.001
      self.activate_camera("b_bot_inside_camera")
      self.simple_pick("b_bot", goal, gripper_force=100.0, grasp_width=.05, axis="z")

      b_bot_before_hole = [1.196680545, -1.73023905, 1.934368435, -1.774223466, -1.543027226, 1.17229890]
      self.move_joints("b_bot", b_bot_before_hole)
      success_b = self.load_program(robot="b_bot", program_name="wrs2020/shaft_v3.urp", recursion_depth=3)
      
      if success_b:
        print("Loaded shaft program.")
        rospy.sleep(1)
        self.execute_loaded_program(robot="b_bot")
        print("Started execution. Waiting for b_bot to finish.")
      else:
        print("Problem loading. Not executing shaft procedure.")
        return False
      wait_for_UR_program("/b_bot", rospy.Duration.from_sec(50))
      if self.is_robot_protective_stopped("b_bot"):
        rospy.logwarn("Robot was protective stopped after shaft insertion - shaft may be stuck!")
        #TODO: Recovery? Try to loosen the shaft?
        self.unlock_protective_stop("b_bot")
        rospy.sleep(1)
        if self.is_robot_protective_stopped("b_bot"):
          return False
      return True
    
    # ==========================================================
    
    if task_name == "idler pulley":
      self.go_to_named_pose("home","a_bot")
      self.go_to_named_pose("home","b_bot")
      
      goal = self.look_and_get_grasp_point("taskboard_idler_pulley_small")
      if not goal:
        rospy.logerr("Could not find idler pulley in tray. Skipping procedure.")
        return False
      self.activate_camera("b_bot_inside_camera")
      goal.pose.position.x -= 0.01 # MAGIC NUMBER
      goal.pose.position.z = 0.014
      rospy.loginfo("Picking idler pulley at: ")
      self.go_to_named_pose("home","b_bot")
      pick_pose = copy.deepcopy(goal)
      pick_pose.pose.orientation = geometry_msgs.msg.Quaternion(*tf.transformations.quaternion_from_euler(0, tau/4, -tau/4))

      approach_pose = copy.deepcopy(pick_pose)
      approach_pose.pose.position.z += 0.1

      self.open_gripper("a_bot", wait=False)
      self.open_gripper("a_bot", wait=False, opening_width=0.07)
      self.go_to_pose_goal("a_bot", approach_pose, speed=0.2, move_lin = True)
      self.go_to_pose_goal("a_bot", pick_pose, speed=0.1, move_lin = True)

      # # TODO (felixvd): Change this to the special tool without a suction pad
      # if self.do_change_tool_action("b_bot", equip=True, screw_size = 4):
      #   self.go_to_named_pose("home","b_bot")
      # else:
      #   rospy.logerr("Tool could not be picked! Aborting")
      #   return False

      ##### Centering using urp
      centeringgrasp = self.load_program(robot="a_bot", program_name="wrs2020/taskboard_retainer_and_nut_v4_hu.urp", recursion_depth=3)
      if not centeringgrasp:
        rospy.logerr("Failed to load centeringgrasp program on a_bot")
        return False
      print("Running belt pick on a_bot.")
      if not self.execute_loaded_program(robot="a_bot"):
        rospy.logerr("Failed to execute centeringgrasp program on a_bot")
        return False
      wait_for_UR_program("/a_bot", rospy.Duration.from_sec(20))

      self.do_change_tool_action("b_bot", equip=True, screw_size = 4)
      # success_a = self.load_program(robot="a_bot", program_name="wrs2020/tb_retainer_and_nut_v2_hu.urp", recursion_depth=3)
      success_b = self.load_program(robot="b_bot", program_name="wrs2020/taskboard_retainer_and_nut_v4.urp", recursion_depth=3)

      if success_a and success_b:
        print("Loaded idler pulley program.")
        rospy.sleep(1)
        self.execute_loaded_program(robot="a_bot")
        rospy.sleep(20) # abot picks
        self.execute_loaded_program(robot="b_bot")
        rospy.sleep(10) # bbot holds
        self.confirm_to_proceed("Can popup be closed? 1")
        self.close_ur_popup(robot="b_bot")
        self.set_motor("screw_tool_m4", "tighten", duration=20)
        rospy.sleep(22) # bbot fiddles
        self.confirm_to_proceed("Can popup be closed? 2")
        self.close_ur_popup(robot="a_bot")
        rospy.sleep(15) #a bot picks nut
        self.confirm_to_proceed("Can popup be closed? 3")
        self.close_ur_popup(robot="a_bot")
        self.set_motor("screw_tool_m4", "tighten", duration=20)
        rospy.sleep(30) # a bot spirals nut
        self.confirm_to_proceed("Can popups be closed? 4")
        self.close_ur_popup(robot="a_bot")
        self.close_ur_popup(robot="b_bot")
      else:
        print("Problem loading. Not executing idler pulley procedure.")
        return False
      wait_for_UR_program("/b_bot", rospy.Duration.from_sec(10))
      wait_for_UR_program("/a_bot", rospy.Duration.from_sec(10))
      if self.is_robot_protective_stopped("b_bot"):
        # rospy.logwarn("Robot was protective stopped after idler pulley insertion - idler pulley may be stuck!")
        # self.unlock_protective_stop("b_bot")
        self.go_to_named_pose("home","b_bot")
      self.do_change_tool_action("b_bot", equip=False, screw_size = 4)
      self.go_to_named_pose("home","a_bot")
      self.go_to_named_pose("home","b_bot")
      return True
    
if __name__ == '__main__':
  try:
    taskboard = TaskboardClass()
    taskboard.define_tool_collision_objects()

    i = 1
    while i and not rospy.is_shutdown():
      rospy.loginfo("Enter 1 to move robots to home")
      rospy.loginfo("Enter 11, 12 to open/close grippers")
      rospy.loginfo("Enter 13, 14 to equip/unequip m3 screw tool")
      rospy.loginfo("Enter 15, 16 to equip/unequip m4 screw tool")
      # rospy.loginfo("Enter 17, 18 to equip/unequip belt placement tool")
      rospy.loginfo("Subtasks: 51 (set screw), 52 (M3), 53 (M4), 54 (belt), 55 (motor pulley), 56 (shaft), 57 (bearing), 58 (idler pulley)")
      rospy.loginfo("Enter 8 to spawn example parts")
      rospy.loginfo("Enter reset to reset the scene")
      rospy.loginfo("Enter prep to prepare the task (do this before running)")
      rospy.loginfo("Enter ssup/ssdown to fine-tune the set screw tool position")
      rospy.loginfo("Enter start to run the task (competition mode, no confirmations)")
      rospy.loginfo("Enter test for a test run of the task (WITH confirmations)")
      rospy.loginfo("Enter x to exit")
      i = raw_input()
      
      if i == "prep":
        taskboard.prep_taskboard_task()
      if i == "ssup":
        taskboard.at_set_screw_hole.pose.position.z -= 0.001
        taskboard.move_b_bot_to_setscrew_initial_pos()
      if i == "ssdown":
        taskboard.at_set_screw_hole.pose.position.z += 0.001
        taskboard.move_b_bot_to_setscrew_initial_pos()
      if i == "start":
        taskboard.competition_mode = True
        taskboard.full_taskboard_task()
        taskboard.competition_mode = False
      if i == "test":
        taskboard.competition_mode = False
        taskboard.full_taskboard_task()
      if i == "1":
        taskboard.go_to_named_pose("home","a_bot")
        taskboard.go_to_named_pose("home","b_bot")
      if i == "11":
        taskboard.open_gripper("a_bot", wait=False)
        taskboard.open_gripper("b_bot")
      if i == "12":
        taskboard.close_gripper("a_bot", wait=False)
        taskboard.close_gripper("b_bot")
      if i == "13":
        taskboard.do_change_tool_action("a_bot", equip=True, screw_size = 3)
      if i == "14":
        taskboard.do_change_tool_action("a_bot", equip=False, screw_size = 3)
      if i == "15":
        taskboard.do_change_tool_action("b_bot", equip=True, screw_size = 4)
      if i == "16":
        taskboard.do_change_tool_action("b_bot", equip=False, screw_size = 4)
      # if i == "15":
      #   taskboard.equip_unequip_belt_tool(equip=True)
      # if i == "16":
      #   taskboard.equip_unequip_belt_tool(equip=False)
      if i == "51":
        taskboard.do_task("M2 set screw")
      if i == "52":
        taskboard.do_task("M3 screw")
      if i == "53":
        taskboard.do_task("M4 screw")
      if i == "54":
        taskboard.do_task("belt")
      if i == "55":
        taskboard.do_task("motor pulley")
      if i == "56":
        taskboard.do_task("shaft")
      if i == "57":
        taskboard.do_task("bearing")
      if i == "577":
        taskboard.do_task("screw_bearing")
      if i == "575":
        taskboard.align_bearing_holes()
      if i == "58":
        taskboard.do_task("idler pulley")
      if i == "8":
        taskboard.spawn_example_objects()      
      if i == "9":
        taskboard.activate_led("b_bot", on=True)
      if i == "99":
        taskboard.activate_led("b_bot", on=False)
      if i == "d1":
        taskboard.check_for_dead_controller_and_force_start(robot="b_bot")
      if i == "f1":
        pick_pose = geometry_msgs.msg.PoseStamped()
        pick_pose.header.frame_id = "tray_center"
        pick_pose.pose.orientation = geometry_msgs.msg.Quaternion(*tf_conversions.transformations.quaternion_from_euler(0, 0, 0))
        pick_pose.pose.position.x = 0.03
        taskboard.simple_pick("a_bot", pick_pose, approach_height = 0.05, item_id_to_attach = "bearing", lift_up_after_pick=True)
      if i == "f2":
        ps = geometry_msgs.msg.PoseStamped()
        ps.header.frame_id = "tray_center"
        ps.pose.orientation = geometry_msgs.msg.Quaternion(*tf_conversions.transformations.quaternion_from_euler(0, 0, 0))
        ps.pose.position.z = -0.15
        taskboard.go_to_pose_goal("a_bot", ps, speed=0.1, end_effector_link="bearing/back_hole", move_lin = False)
      if i == "reset":
        taskboard.reset_scene_and_robots()
      if i == "x":
        break
      i = True

    print "============ Done!"
  except rospy.ROSInterruptException:
    pass

