import rospy
import actionlib
from o2ac_msgs import msg as omsg

#########################################################################
#  class PoseEstimationClient                                           #
#########################################################################
class PoseEstimationClient(object):
    def __init__(self, server=''):
        super(PoseEstimationClient, self).__init__()
        self._client \
            = actionlib.SimpleActionClient(server + '/poseEstimationTest',
                                           omsg.poseEstimationTestAction)
        self._client.wait_for_server()

    def trigger(self, object_id='', camera_id=''):
        goal = omsg.poseEstimationTestGoal(object_id=object_id,
                                           camera_id=camera_id)
        self._client.send_goal(goal)

    def get_results(self, timeout=rospy.Duration()):
        if (not self._client.wait_for_result(timeout)):
            self._client.cancel_goal()  # Cancel if timeout expired

        return self._client.get_result().pose_estimation_result_list

#########################################################################
#  class BeltDetectionClient                                            #
#########################################################################
class BeltDetectionClient(object):
    def __init__(self, server=''):
        super(BeltDetectionClient, self).__init__()
        self._client \
            = actionlib.SimpleActionClient(server + '/beltDetectionTest',
                                           omsg.beltDetectionTestAction)
        self._client.wait_for_server()

    def trigger(self, object_id='', camera_id=''):
        goal = omsg.beltDetectionTestGoal(object_id=object_id,
                                          camera_id=camera_id)
        self._client.send_goal(goal)

    def get_grasp_points(self, timeout=rospy.Duration()):
        if (not self._client.wait_for_result(timeout)):
            self._client.cancel_goal()  # Cancel if timeout expired

        return self._client.get_result().grasp_points
