/*
 *  \file	KLTTracker.h
 *  \author	Toshio UESHIBA
 *  \brief	ROS node for tracking corners in 2D images
 */
#include <ros/ros.h>
#include <std_srvs/Trigger.h>
#include <image_transport/image_transport.h>
#include <message_filters/subscriber.h>
#include <message_filters/synchronizer.h>
#include <message_filters/sync_policies/approximate_time.h>
#include <ddynamic_reconfigure/ddynamic_reconfigure.h>
#include "klt/klt.h"

namespace aist_visual_tracker
{
/************************************************************************
*  class KLTTracker							*
************************************************************************/
class KLTTracker
{
  private:
    using camera_info_t	 = sensor_msgs::CameraInfo;
    using camera_info_cp = sensor_msgs::CameraInfoConstPtr;
    using image_t	 = sensor_msgs::Image;
    using image_cp	 = sensor_msgs::ImageConstPtr;
    using sync_policy_t	 = message_filters::sync_policies::
			     ApproximateTime<camera_info_t, image_t>;
    using sync_policy2_t = message_filters::sync_policies::
			     ApproximateTime<camera_info_t, image_t, image_t>;
    using context_t	 = KLT_TrackingContextRec;
    
  public:
		KLTTracker(const ros::NodeHandle& nh)			;
		~KLTTracker()						;
    
    void	run()							;

  private:
  // Service callbacks
    bool	select_cb(std_srvs::Trigger::Request&  req,
			  std_srvs::Trigger::Response& res)		;

  // ddynamic_reconfigure callbacks
    void	set_window_radius_cb(int context_t::* width,
				     int context_t::* height,
				     int radius)			;
    void	set_sequential_mode_cb(bool enable)			;
    template <class T>
    void	set_ctx_cb(T context_t::* field, T value)		;
    template <class T>
    void	set_param_cb(T KLTTracker::* field, T value,
			     bool select)				;

  // topic callbacks
    void	track_cb(const camera_info_cp& camera_info,
			 const image_cp& image)				;
    void	track_with_depth_cb(const camera_info_cp& camera_info,
				    const image_cp& image,
				    const image_cp& depth)		;

    void	track(const image_t& image)				;
    
    size_t	nfeatures()	const	{ return _featureTable->nFeatures; }
    size_t	nframes()	const	{ return _featureTable->nFrames; }
    KLT_Feature	operator [](size_t j)				const	;
    KLT_Feature	operator ()(size_t i, size_t j)			const	;
    void	selectGoodFeatures(const image_t& image)		;
    void	trackFeatures(const image_t& image)			;
    KLT_FeatureList
		featureList()		{ return _featureList; }
	
  private:
    ros::NodeHandle					_nh;

    const ros::ServiceServer				_select_srv;

    message_filters::Subscriber<camera_info_t>		_camera_info_sub;
    message_filters::Subscriber<image_t>		_image_sub;
    message_filters::Subscriber<image_t>		_depth_sub;
    message_filters::Synchronizer<sync_policy_t>	_sync;
    message_filters::Synchronizer<sync_policy2_t>	_sync2;

    image_transport::ImageTransport			_it;
    const image_transport::Publisher			_image_pub;

  // Tracker parameters and dynamic_reconfigure server for setting them
    ddynamic_reconfigure::DDynamicReconfigure		_ddr;
    int							_nfeatures;
    int							_nframes;
    bool						_replace;

  // Tracker stuffs
    KLT_TrackingContext					_ctx;
    KLT_FeatureList					_featureList;
    KLT_FeatureTable					_featureTable;
    bool						_select;
    size_t						_frame;
    int							_previous_width;
    int							_previous_height;
    int							_marker_size;
    int							_marker_thickness;
};

inline KLT_Feature
KLTTracker::operator [](size_t j) const
{
    return _featureTable->feature[j][_frame];
}
	 
}	// namespace aist_visual_tracker
