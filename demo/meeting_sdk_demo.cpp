#include <limits.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>
#include <glib.h>
#include <glib-unix.h>
#include "MediaValidation.h"
#include "SdkControlServer.h"
#include <sstream>
#include <thread>
#include <sys/syscall.h>
#include <sys/syscall.h>
#include <fstream>
#include <iosfwd>
#include <iostream>
#include <map>
#include <algorithm>
#include <cmath>

#include "zoom_sdk.h"
#include "auth_service_interface.h"
#include "meeting_service_interface.h"
#include "meeting_service_components/meeting_audio_interface.h"
#include "meeting_service_components/meeting_participants_ctrl_interface.h"
#include "meeting_service_components/meeting_video_interface.h"
#include "setting_service_interface.h"



//used to accept prompts
#include "MeetingReminderEventListener.h"
//used to listen to callbacks from meeting related matters
#include "MeetingServiceEventListener.h"
//used to listen to callbacks from authentication related matters
#include "AuthServiceEventListener.h"
//used for connection helper
#include "NetworkConnectionHandler.h"

//used for event listener
#include "MeetingParticipantsCtrlEventListener.h"
#include "MeetingRecordingCtrlEventListener.h"

//references for GetVideoRawData
#include "ZoomSDKRenderer.h"
#include "rawdata/rawdata_renderer_interface.h"
#include "rawdata/zoom_rawdata_api.h"

//references for GetAudioRawData
#include "ZoomSDKAudioRawData.h"
#include "meeting_service_components/meeting_recording_interface.h"

//references for SendVideoRawData
#include "ZoomSDKVideoSource.h"

//references for SendAudioRawData
#include "ZoomSDKVirtualAudioMicEvent.h"

#include <mutex>


USING_ZOOM_SDK_NAMESPACE


//references for SendAudioRawData
std::string DEFAULT_AUDIO_SOURCE = "/app/media/video.mp4";
ZoomSDKVirtualAudioMicEvent* virtual_microphone_source = nullptr;
std::shared_ptr<PlaybackClock> playback_clock;
unsigned int audio_start_attempts = 0;
bool audio_started = false;
std::atomic<bool> music_audio_configured{false};
unsigned int music_audio_attempts = 0;

//references for SendVideoRawData
std::string DEFAULT_VIDEO_SOURCE = "/app/media/video.mp4";
ZoomSDKVideoSource* virtual_camera_source = nullptr;
bool camera_registered = false, microphone_registered = false;


GMainLoop* loop;
bool shutdown_requested = false;
int playback_control_fd = -1;
const char* playback_control_path = "/tmp/zoom-playback-control";
std::string playback_control_buffer;
std::string current_playback_id;
int app_exit_code = 0;
void OnSDKFailure(int code) {
	std::cerr << "Stopping after SDK failure, code: " << code << std::endl;
	app_exit_code = 1;
	if (loop) g_main_loop_quit(loop);
}


//These are needed to readsettingsfromTEXT named config.txt
std::string meeting_number, token, meeting_password, recording_token,onBehalfOf_Token;
std::string participant_name = "VideoBot";


//Services which are needed to initialize, authenticate and configure settings for the SDK
ZOOM_SDK_NAMESPACE::IAuthService* m_pAuthService;
ZOOM_SDK_NAMESPACE::IMeetingService* m_pMeetingService;
ZOOM_SDK_NAMESPACE::ISettingService* m_pSettingService;
INetworkConnectionHelper* network_connection_helper;

//references for GetVideoRawData
ZoomSDKRenderer* videoSource = new ZoomSDKRenderer();
IZoomSDKRenderer* videoHelper;
IMeetingRecordingController* m_pRecordController;
IMeetingParticipantsController* m_pParticipantsController;


//references for GetAudioRawData
ZoomSDKAudioRawData* audio_source = new ZoomSDKAudioRawData();
IZoomSDKAudioRawDataHelper* audioHelper;

//this is used to get a userID, there is no specific proper logic here. It just gets the first userID.
//userID is needed for video subscription.
unsigned int userID;





//this will enable or disable logic to get raw video and raw audio
//do note that this will be overwritten by config.txt
bool GetVideoRawData = true;
bool GetAudioRawData = true;
bool SendVideoRawData = false;
bool SendAudioRawData = false;


//this is a helper method to get the first User ID, it is just an arbitary UserID
uint32_t getUserID() {
	m_pParticipantsController = m_pMeetingService->GetMeetingParticipantsController();
	int returnvalue = m_pParticipantsController->GetParticipantsList()->GetItem(0);
	std::cout << "UserID is : " << returnvalue << std::endl;
	return returnvalue;
}

IUserInfo* getMyself() {
	m_pParticipantsController = m_pMeetingService->GetMeetingParticipantsController();
	IUserInfo* returnvalue = m_pParticipantsController->GetMySelfUser();
	//std::cout << "UserID is : " << returnvalue << std::endl;
	return returnvalue;
}

//this is a helper method to get the first User Object, it is just an arbitary User Object
IUserInfo* getUserObj() {
	m_pParticipantsController = m_pMeetingService->GetMeetingParticipantsController();
	int userID = m_pParticipantsController->GetParticipantsList()->GetItem(0);
	IUserInfo* returnvalue = m_pParticipantsController->GetUserByUserID(userID);
	std::cout << "UserID is : " << returnvalue << std::endl;
	return returnvalue;
}

//check if you have permission to start raw recording
void CheckAndStartRawRecording(bool isVideo, bool isAudio) {

	if (isVideo || isAudio) {
		m_pRecordController = m_pMeetingService->GetMeetingRecordingController();
		SDKError err2 = m_pMeetingService->GetMeetingRecordingController()->CanStartRawRecording();

		if (err2 == SDKERR_SUCCESS) {
			SDKError err1 = m_pRecordController->StartRawRecording();
			if (err1 != SDKERR_SUCCESS) {
				std::cout << "Error occurred starting raw recording" << std::endl;
			}
			else {
				//GetVideoRawData
				if (isVideo) {
					SDKError err = createRenderer(&videoHelper, videoSource);
					if (err != SDKERR_SUCCESS) {
						std::cout << "Error occurred" << std::endl;
						// Handle error
					}
					else {
						std::cout << "attemptToStartRawRecording : subscribing" << std::endl;
						videoHelper->setRawDataResolution(ZoomSDKResolution_720P);
						videoHelper->subscribe(getUserID(), RAW_DATA_TYPE_VIDEO);
					}
				}
				//GetAudioRawData
				if (isAudio) {
					audioHelper = GetAudioRawdataHelper();
					if (audioHelper) {
						SDKError err = audioHelper->subscribe(audio_source);
						if (err != SDKERR_SUCCESS) {
							std::cout << "Error occurred subscribing to audio : " << err << std::endl;
						}
					}
					else {
						std::cout << "Error getting audioHelper" << std::endl;
					}
				}
			}
		}
		else {
			std::cout << "Cannot start raw recording: no permissions yet, need host, co-host, or recording privilege" << std::endl;
		}
	}
}

void ConfigureMusicAudio() {
	if (!m_pSettingService) return;
	const auto settings = m_pSettingService->GetAudioSettings();
	if (!settings) return;
	const auto originalResult = settings->EnableMicOriginalInput(true);
	music_audio_configured = originalResult == SDKERR_SUCCESS;
	std::cout << "VoIP original sound, SDK result: " << originalResult << std::endl;
	std::cout << "VoIP disable echo cancellation, SDK result: " << settings->DisableEchoCancellation(true) << std::endl;
	std::cout << "VoIP disable auto gain, SDK result: " << settings->EnableAutoAdjustMic(false) << std::endl;
}

//check if you meet the requirements to send raw data
void CheckAndStartRawSending(bool isVideo, bool isAudio) {
	if (!isVideo && !isAudio) return;
	if (!playback_clock) playback_clock = std::make_shared<PlaybackClock>(isVideo, isAudio);


	//SendVideoRawData
	if (isVideo) {

		if (!virtual_camera_source) virtual_camera_source = new ZoomSDKVideoSource(DEFAULT_VIDEO_SOURCE, playback_clock);
		IZoomSDKVideoSourceHelper* p_videoSourceHelper = GetRawdataVideoSourceHelper();

		if (p_videoSourceHelper) {
			SDKError err = p_videoSourceHelper->setExternalVideoSource(virtual_camera_source, FrameDataFormat_I420_LIMITED);
            camera_registered = err == SDKERR_SUCCESS;



			if (err != SDKERR_SUCCESS) {
				printf("attemptToStartRawVideoSending(): Failed to set external video source, error code: %d\n", err);
			}
			else {
				printf("attemptToStartRawVideoSending(): Success \n");
				IMeetingVideoController* meetingController = m_pMeetingService->GetMeetingVideoController();
				meetingController->UnmuteVideo();

			}
		}
		else {
			printf("attemptToStartRawVideoSending(): Failed to get video source helper\n");
		}
	}


	//SendAudioRawData
	if (isAudio) {
		if (!virtual_microphone_source) virtual_microphone_source = new ZoomSDKVirtualAudioMicEvent(DEFAULT_AUDIO_SOURCE, playback_clock, ConfigureMusicAudio);
		IZoomSDKAudioRawDataHelper* audioHelper = GetAudioRawdataHelper();
		if (audioHelper) {
			SDKError err = audioHelper->setExternalAudioSource(virtual_microphone_source);
            microphone_registered = err == SDKERR_SUCCESS;
			std::cout << "Register external microphone, SDK result: " << err << std::endl;
			m_pMeetingService->GetMeetingAudioController()->JoinVoip();
		}
		else {
			std::cerr << "Cannot obtain external microphone helper." << std::endl;
		}
	}


}



//callback when given host permission
void onIsHost() {
	printf("Is host now...\n");
	CheckAndStartRawRecording(GetVideoRawData, GetAudioRawData);
}

//callback when given cohost permission
void onIsCoHost() {
	printf("Is co-host now...\n");
	CheckAndStartRawRecording(GetVideoRawData, GetAudioRawData);
}
//callback when given recording permission
void onIsGivenRecordingPermission() {
	printf("Is given recording permissions now...\n");
	CheckAndStartRawRecording(GetVideoRawData, GetAudioRawData);
}

void turnOnSendVideoAndAudio() {
	//testing WIP
	if (SendVideoRawData) {
		IMeetingVideoController* meetingVidController = m_pMeetingService->GetMeetingVideoController();
		meetingVidController->UnmuteVideo();
	}
	//testing WIP
	if (SendAudioRawData) {
		IMeetingAudioController* meetingAudController = m_pMeetingService->GetMeetingAudioController();
		meetingAudController->JoinVoip();
		printf("Is my audio muted: %d\n", getMyself()->IsAudioMuted());
		meetingAudController->UnMuteAudio(getMyself()->GetUserID());
	}
}
void turnOffSendVideoandAudio() {
	//testing WIP
	if (SendVideoRawData) {
		IMeetingVideoController* meetingVidController = m_pMeetingService->GetMeetingVideoController();
		meetingVidController->MuteVideo();
	}
	//testing WIP
	if (SendAudioRawData) {
		IMeetingAudioController* meetingAudController = m_pMeetingService->GetMeetingAudioController();
		meetingAudController->MuteAudio(getMyself()->GetUserID(), true);

	}
}


//callback when the SDK is inmeeting
void onInMeeting() {

	printf("onInMeeting Invoked\n");

	//double check if you are in a meeting
	if (m_pMeetingService->GetMeetingStatus() == ZOOM_SDK_NAMESPACE::MEETING_STATUS_INMEETING) {
		printf("In Meeting Now...\n");

		//print all list of participants
		IList<unsigned int>* participants = m_pMeetingService->GetMeetingParticipantsController()->GetParticipantsList();
		printf("Participants count: %d\n", participants->GetCount());
	}

	//first attempt to start raw recording  / sending, upon successfully joined and achieved "in-meeting" state.
	CheckAndStartRawRecording(GetVideoRawData, GetAudioRawData);
	CheckAndStartRawSending(SendVideoRawData, SendAudioRawData);

}

//on meeting ended, typically by host, do something here. it is possible to reuse this SDK instance
void onMeetingEndsQuitApp() {
	if (loop) g_main_loop_quit(loop);
}

void onMeetingJoined() {

	printf("Joining Meeting...\n");
}

//get path, helper method used to read json config file
std::string getSelfDirPath()
{
	char dest[PATH_MAX];
	memset(dest, 0, sizeof(dest)); // readlink does not null terminate!
	if (readlink("/proc/self/exe", dest, PATH_MAX) == -1)
	{
	}
	char* tmp = strrchr(dest, '/');
	if (tmp)
		*tmp = 0;
	printf("getpath\n");
	return std::string(dest);
}


// Function to process a line containing a key-value pair
void processLine(const std::string& line, std::map<std::string, std::string>& config) {
	// Find the position of the ':' character
	size_t colonPos = line.find(':');

	if (colonPos != std::string::npos) {
		// Extract the key and value parts
		std::string key = line.substr(0, colonPos);
		std::string value = line.substr(colonPos + 1);

		// Remove leading/trailing whitespaces from the key and value
		key.erase(0, key.find_first_not_of(" \t"));
		key.erase(key.find_last_not_of(" \t") + 1);
		value.erase(0, value.find_first_not_of(" \t"));
		value.erase(value.find_last_not_of(" \t") + 1);

		// Remove double-quote characters and carriage return ('\r') from the value
		value.erase(std::remove_if(value.begin(), value.end(), [](char c) { return c == '"' || c == '\r'; }), value.end());

		// Store the key-value pair in the map
		config[key] = value;
	}
}

void ReadTEXTSettings()
{
	
	std::string self_dir = getSelfDirPath();
	printf("self path: %s\n", self_dir.c_str());
	self_dir.append("/config.txt");

	std::ifstream configFile(self_dir.c_str());
	if (!configFile) {
		std::cerr << "Error opening config file." << std::endl;
		std::exit(1);
	}
	else{

		std::cerr << "Readfile success." << std::endl;
	}

	std::map<std::string, std::string> config;
	std::string line;

	while (std::getline(configFile, line)) {
		// Process each line to extract key-value pairs
		processLine(line, config);
		
	}

	// Example: Accessing values by key
	if (config.find("meeting_number") != config.end()) {
		
		meeting_number=config["meeting_number"];
	}
	if (config.find("token") != config.end()) {
		 token=config["token"];
	}
	if (config.find("meeting_password") != config.end()) {
		
		meeting_password=config["meeting_password"];
	}
	if (config.find("recording_token") != config.end()) {
	
		 recording_token=config["recording_token"];
	}
	if (config.find("onBehalfOf_Token") != config.end()) {
	
		 onBehalfOf_Token=config["onBehalfOf_Token"];
	}


	if (config.find("GetVideoRawData") != config.end()) {
		std::cout << "GetVideoRawData before parsing is : " << config["GetVideoRawData"]   << std::endl;
		
	if (config["GetVideoRawData"] == "true"){
			GetVideoRawData=true;
		}
		else{
			GetVideoRawData=false;
		}
		std::cout << "GetVideoRawData: " << GetVideoRawData << std::endl;
	}
	if (config.find("GetAudioRawData") != config.end()) {
		std::cout << "GetAudioRawData before parsing is : " << config["GetAudioRawData"]  << std::endl;
		
		if (config["GetAudioRawData"] == "true"){
			GetAudioRawData=true;
		}
		else{
			GetAudioRawData=false;
		}
		std::cout << "GetAudioRawData: " << GetAudioRawData << std::endl;
	}

	if (config.find("SendVideoRawData") != config.end()) {
		std::cout << "SendVideoRawData before parsing is : " << config["SendVideoRawData"] << std::endl;

		if (config["SendVideoRawData"] == "true") {
			SendVideoRawData = true;
		}
		else {
			SendVideoRawData = false;
		}
		std::cout << "SendVideoRawData: " << SendVideoRawData << std::endl;
	}
	if (config.find("SendAudioRawData") != config.end()) {
		std::cout << "SendAudioRawData before parsing is : " << config["SendAudioRawData"] << std::endl;

		if (config["SendAudioRawData"] == "true") {
			SendAudioRawData = true;
		}
		else {
			SendAudioRawData = false;
		}
		std::cout << "SendAudioRawData: " << SendAudioRawData << std::endl;
	}

	if (config.count("participant_name")) participant_name = config["participant_name"];
	if (config.count("video_source")) DEFAULT_VIDEO_SOURCE = config["video_source"];
	DEFAULT_AUDIO_SOURCE = DEFAULT_VIDEO_SOURCE;
	if (meeting_number.empty() || meeting_number.size() > 11 ||
		meeting_number.find_first_not_of("0123456789") != std::string::npos ||
		meeting_number.find_first_not_of('0') == std::string::npos || token.empty() || participant_name.empty()) {
		std::cerr << "Invalid configuration: require a numeric meeting_number (1-11 digits), token and participant_name." << std::endl;
		std::exit(1);
	}

	printf("directory of config file: %s\n", self_dir.c_str());


}


void CleanSDK()
{
	ZOOM_SDK_NAMESPACE::SDKError err(ZOOM_SDK_NAMESPACE::SDKERR_SUCCESS);
	if (videoHelper) {
		videoHelper->unSubscribe();
		destroyRenderer(videoHelper);
		videoHelper = nullptr;
	}
	if (audioHelper) { audioHelper->unSubscribe(); audioHelper = nullptr; }
	if (m_pMeetingService) {
		ZOOM_SDK_NAMESPACE::DestroyMeetingService(m_pMeetingService);
		m_pMeetingService = nullptr;
	}

	if (m_pAuthService)
	{
		ZOOM_SDK_NAMESPACE::DestroyAuthService(m_pAuthService);
		m_pAuthService = NULL;
	}
	if (m_pSettingService)
	{
		ZOOM_SDK_NAMESPACE::DestroySettingService(m_pSettingService);
		m_pSettingService = NULL;
	}
	//if (_network_connection_helper)
	//{
	//	ZOOM_SDK_NAMESPACE::DestroyNetworkConnectionHelper(_network_connection_helper);
	//	_network_connection_helper = NULL;
	//}
	//attempt to clean up SDK
	err = ZOOM_SDK_NAMESPACE::CleanUPSDK();
	if (err != ZOOM_SDK_NAMESPACE::SDKERR_SUCCESS)
	{
		std::cerr << "CleanSDK meetingSdk:error " << std::endl;
	}
	else
	{
		std::cerr << "CleanSDK meetingSdk:success" << std::endl;
	}
}

void changeMicrophoneAndSpeaker() {
	ZOOM_SDK_NAMESPACE::IAudioSettingContext* pAudioContext = m_pSettingService->GetAudioSettings();
	if (pAudioContext)
	{
		//setting speaker
		//if there are speakers detected
		if (pAudioContext->GetSpeakerList()->GetCount() >= 1) {
			std::cout << "Number of speaker(s) : " << pAudioContext->GetSpeakerList()->GetCount() << std::endl;
			ISpeakerInfo* sInfo = pAudioContext->GetSpeakerList()->GetItem(0);
			const zchar_t* deviceName = sInfo->GetDeviceName();

			//set speaker
			if (deviceName != nullptr && deviceName[0] != '\0') {
				std::cout << "Speaker(0) name : " << sInfo->GetDeviceName() << std::endl;
				std::cout << "Speaker(0) id : " << sInfo->GetDeviceId() << std::endl;
				pAudioContext->SelectSpeaker(sInfo->GetDeviceId(), sInfo->GetDeviceName());
				std::cout << "Is selected speaker? : " << pAudioContext->GetSpeakerList()->GetItem(0)->IsSelectedDevice() << std::endl;
			}
			else {
				std::cout << "Speaker(0) name is empty or null." << std::endl;
				std::cout << "Speaker(0) id is empty or null." << std::endl;
			}
		}

		//setting microphone
		//if there are microphone detected
		if (pAudioContext->GetMicList()->GetCount() >= 1) {
			IMicInfo* mInfo = pAudioContext->GetMicList()->GetItem(0);
			std::cout << "Number of mic(s) : " << pAudioContext->GetMicList()->GetCount() << std::endl;
			const zchar_t* deviceName = mInfo->GetDeviceName();

			//set microphone
			if (deviceName != nullptr && deviceName[0] != '\0') {
				std::cout << "Mic(0) name : " << mInfo->GetDeviceName() << std::endl;
				std::cout << "Mic(0) id : " << mInfo->GetDeviceId() << std::endl;
				pAudioContext->SelectMic(mInfo->GetDeviceId(), mInfo->GetDeviceName());
				std::cout << "Is selected Mic? : " << pAudioContext->GetMicList()->GetItem(0)->IsSelectedDevice() << std::endl;
			}
			else {
				std::cout << "Mic(0) name is empty or null." << std::endl;
				std::cout << "Mic(0) id is empty or null." << std::endl;
			}
		}
	}
}

void JoinMeeting()
{
	std::cerr << "Joining Meeting" << std::endl;
	SDKError err2(SDKError::SDKERR_SUCCESS);

	//try to create the meetingservice object, 
	//this object will be used to join the meeting
	if ((err2 = CreateMeetingService(&m_pMeetingService)) != SDKError::SDKERR_SUCCESS) { OnSDKFailure(err2); return; }
	std::cerr << "MeetingService created." << std::endl;

	//before joining a meeting, create the setting service
	//this object is used to for settings
	if ((err2 = CreateSettingService(&m_pSettingService)) != SDKERR_SUCCESS) { OnSDKFailure(err2); return; }
	std::cerr << "Settingservice created." << std::endl;

	// Set the event listener for meeting status
	m_pMeetingService->SetEvent(new MeetingServiceEventListener(&onMeetingJoined, &onMeetingEndsQuitApp, &onInMeeting, &OnSDKFailure));

	// Set the event listener for host, co-host 
	m_pParticipantsController = m_pMeetingService->GetMeetingParticipantsController();
	m_pParticipantsController->SetEvent(new MeetingParticipantsCtrlEventListener(&onIsHost, &onIsCoHost));

	// Set the event listener for recording privilege status
	m_pRecordController = m_pMeetingService->GetMeetingRecordingController();
	m_pRecordController->SetEvent(new MeetingRecordingCtrlEventListener(&onIsGivenRecordingPermission));


	// set event listnener for prompt handler 
	IMeetingReminderController* meetingremindercontroller = m_pMeetingService->GetMeetingReminderController();
	MeetingReminderEventListener* meetingremindereventlistener = new MeetingReminderEventListener();
	meetingremindercontroller->SetEvent(meetingremindereventlistener);

	//prepare params used for joining meeting
	ZOOM_SDK_NAMESPACE::JoinParam joinParam{};
	ZOOM_SDK_NAMESPACE::SDKError err(ZOOM_SDK_NAMESPACE::SDKERR_SERVICE_FAILED);
	joinParam.userType = ZOOM_SDK_NAMESPACE::SDK_UT_WITHOUT_LOGIN;
	ZOOM_SDK_NAMESPACE::JoinParam4WithoutLogin& withoutloginParam = joinParam.param.withoutloginuserJoin;
	// withoutloginParam.meetingNumber = 1231231234;
	withoutloginParam.meetingNumber = std::stoull(meeting_number);
	withoutloginParam.vanityID = NULL;
	withoutloginParam.userName = participant_name.c_str();
	// withoutloginParam.psw = "1";
	withoutloginParam.psw = meeting_password.c_str();
	withoutloginParam.customer_key = NULL;
	withoutloginParam.webinarToken = NULL;
	withoutloginParam.isVideoOff = !SendVideoRawData;
	withoutloginParam.isAudioOff = !SendAudioRawData;


	//automatically set app_privilege token if it is present in config.txt, or retrieved from web service
	withoutloginParam.app_privilege_token = NULL;
	if (!recording_token.size() == 0)
	{
		withoutloginParam.app_privilege_token = recording_token.c_str();
		std::cerr << "Setting recording token" << std::endl;
	}
	else
	{
		withoutloginParam.app_privilege_token = NULL;
		std::cerr << "Leaving recording token as NULL" << std::endl;
	}
	
	//automatically set onBehalfOf token if it is present in config.txt, or retrieved from web service
	withoutloginParam.onBehalfToken = NULL;
	if (!onBehalfOf_Token.size() == 0)
	{
		withoutloginParam.onBehalfToken = onBehalfOf_Token.c_str();
		std::cerr << "Setting onBehalfOf token" << std::endl;
	}
	else
	{
		withoutloginParam.onBehalfToken = NULL;
		std::cerr << "Leaving onBehalfOf token as NULL" << std::endl;
	}



	if (GetAudioRawData) {
		//set join audio to true
		ZOOM_SDK_NAMESPACE::IAudioSettingContext* pAudioContext = m_pSettingService->GetAudioSettings();
		if (pAudioContext)
		{
			//ensure auto join audio
			pAudioContext->EnableAutoJoinAudio(true);
		}
	}
	if (SendVideoRawData) {

		//ensure video is turned on
		withoutloginParam.isVideoOff = false;
		//set join video to true
		ZOOM_SDK_NAMESPACE::IVideoSettingContext* pVideoContext = m_pSettingService->GetVideoSettings();
		if (pVideoContext)
		{
			pVideoContext->EnableAutoTurnOffVideoWhenJoinMeeting(false);
		}
	}
	if (SendAudioRawData) {

		ZOOM_SDK_NAMESPACE::IAudioSettingContext* pAudioContext = m_pSettingService->GetAudioSettings();
		if (pAudioContext)
		{
			//ensure auto join audio
			pAudioContext->EnableAutoJoinAudio(true);
			pAudioContext->EnableAlwaysMuteMicWhenJoinVoip(false);

		}
	}


		//attempt to join meeting
		if (m_pMeetingService)
		{
			err = m_pMeetingService->Join(joinParam);
		}
		else
		{
			std::cout << "join_meeting m_pMeetingService:Null" << std::endl;
		}

		if (ZOOM_SDK_NAMESPACE::SDKERR_SUCCESS == err)
		{
			std::cout << "join_meeting:success" << std::endl;
		}
		else
		{
			std::cout << "join_meeting:error" << std::endl;
			OnSDKFailure(err);
		}
	
}

void LeaveMeeting()
{
	ZOOM_SDK_NAMESPACE::MeetingStatus status = ZOOM_SDK_NAMESPACE::MEETING_STATUS_FAILED;


		if (NULL == m_pMeetingService)
		{

			std::cout << "leave_meeting m_pMeetingService:Null" << std::endl;
		
		}
		else
		{
			status = m_pMeetingService->GetMeetingStatus();
		}

	if (status == ZOOM_SDK_NAMESPACE::MEETING_STATUS_IDLE ||
			status == ZOOM_SDK_NAMESPACE::MEETING_STATUS_ENDED ||
			status == ZOOM_SDK_NAMESPACE::MEETING_STATUS_FAILED)
		{

			std::cout << "LeaveMeeting() not in meeting " << std::endl;
			return;
			
		}

		if (SDKError::SDKERR_SUCCESS == m_pMeetingService->Leave(ZOOM_SDK_NAMESPACE::LEAVE_MEETING))
		{
			std::cout << "LeaveMeeting() success " << std::endl;
		
		}
		else
		{
			std::cout << "LeaveMeeting() error" << std::endl;
			
		}



}

//callback when authentication is compeleted
void OnAuthenticationComplete()
{
	std::cout << "OnAuthenticationComplete" << std::endl;
	JoinMeeting();
}

void AuthMeetingSDK()
{
	SDKError err(SDKError::SDKERR_SUCCESS);

	//create auth service
	if ((err = CreateAuthService(&m_pAuthService)) != SDKError::SDKERR_SUCCESS) { OnSDKFailure(err); return; }
	std::cerr << "AuthService created." << std::endl;

	//Create a param to insert jwt token
	ZOOM_SDK_NAMESPACE::AuthContext param{};

	//set the event listener for onauthenticationcompleted
	if ((err = m_pAuthService->SetEvent(new AuthServiceEventListener(&OnAuthenticationComplete, &OnSDKFailure))) != SDKError::SDKERR_SUCCESS) { OnSDKFailure(err); return; }
	std::cout << "AuthServiceEventListener added." << std::endl;


	if (!token.size() == 0){
		param.jwt_token = token.c_str();
		std::cerr << "AuthSDK: token loaded from configuration" << std::endl;
	}
	if ((err = m_pAuthService->SDKAuth(param)) != SDKERR_SUCCESS) OnSDKFailure(err);
	////attempt to authenticate
	//ZOOM_SDK_NAMESPACE::SDKError sdkErrorResult = m_pAuthService->SDKAuth(param);

	//if (ZOOM_SDK_NAMESPACE::SDKERR_SUCCESS != sdkErrorResult){
	//	std::cerr << "AuthSDK:error " << std::endl;
	//}
	//else{
	//	std::cerr << "AuthSDK:send success, awaiting callback " << std::endl;
	//}
}

void InitMeetingSDK()
{
	ZOOM_SDK_NAMESPACE::SDKError err(ZOOM_SDK_NAMESPACE::SDKERR_SUCCESS);
	ZOOM_SDK_NAMESPACE::InitParam initParam{};

	// set domain
	initParam.strWebDomain = "https://zoom.us";
	initParam.strSupportUrl = "https://zoom.us";

	// set language id
	initParam.emLanguageID = ZOOM_SDK_NAMESPACE::LANGUAGE_English;

	//set logging perferences
	initParam.enableLogByDefault = true;
	initParam.enableGenerateDump = true;

	// attempt to initialize
	err = ZOOM_SDK_NAMESPACE::InitSDK(initParam);
	if (err != ZOOM_SDK_NAMESPACE::SDKERR_SUCCESS){
		std::cerr << "Init meetingSdk:error " << std::endl;
		OnSDKFailure(err);
	}
	else{
		std::cerr << "Init meetingSdk:success" << std::endl;
		const zchar_t* sdk_version = ZOOM_SDK_NAMESPACE::GetSDKVersion();
		if (sdk_version != nullptr) {
			std::cerr << "Meeting SDK Version: " << sdk_version << std::endl;
		}
		else {
			std::cerr << "Meeting SDK Version: unavailable" << std::endl;
		}
	}

	//use connection helper
	//if ((err = CreateNetworkConnectionHelper(&network_connection_helper)) == SDKError::SDKERR_SUCCESS) {
	//	std::cout << "CreateNetworkConnectionHelper created." << std::endl;
	//}
	//if ((err = network_connection_helper->RegisterNetworkConnectionHandler(new NetworkConnectionHandler(&AuthMeetingSDK))) == SDKError::SDKERR_SUCCESS) {
	//	std::cout << "NetworkConnectionHandler registered. Detecting proxy." << std::endl;
	//}
}




//used for non headless app 

void StartMeeting()
{

	ZOOM_SDK_NAMESPACE::StartParam startParam;
	startParam.userType = ZOOM_SDK_NAMESPACE::SDK_UT_NORMALUSER;
	startParam.param.normaluserStart.vanityID = NULL;
	startParam.param.normaluserStart.customer_key = NULL;
	startParam.param.normaluserStart.isVideoOff = false;
	startParam.param.normaluserStart.isAudioOff = false;


	ZOOM_SDK_NAMESPACE::SDKError err = m_pMeetingService->Start(startParam);
	if (SDKError::SDKERR_SUCCESS == err)
	{
		std::cerr << "StartMeeting:success " << std::endl;
	}
	else
	{
		std::cerr << "StartMeeting:error " << std::endl;
	}
}


// Define a struct to hold the response data
struct ResponseData {
	std::ostringstream stream;
};

// Callback function to write response data into the stringstream
static size_t WriteCallback(void* contents, size_t size, size_t nmemb, void* userp) {
	size_t totalSize = size * nmemb;
	ResponseData* response = static_cast<ResponseData*>(userp);
	response->stream.write(static_cast<const char*>(contents), totalSize);
	return totalSize;
}


gboolean timeout_callback(gpointer data)
{
	if (!shutdown_requested && virtual_microphone_source && virtual_microphone_source->IsSending() &&
		!music_audio_configured && music_audio_attempts++ < 5) ConfigureMusicAudio();
	if (!shutdown_requested && SendAudioRawData && virtual_microphone_source && m_pMeetingService &&
		m_pMeetingService->GetMeetingStatus() == MEETING_STATUS_INMEETING && !audio_started) {
		if (virtual_microphone_source->IsSending()) audio_started = true;
		else if (audio_start_attempts++ < 15) {
			const auto myself = getMyself();
			if (myself) {
				const auto result = m_pMeetingService->GetMeetingAudioController()->UnMuteAudio(myself->GetUserID());
				std::cout << "Initial microphone unmute, SDK result: " << result << std::endl;
			}
		}
	}
	if (shutdown_requested && m_pMeetingService) {
		const auto status = m_pMeetingService->GetMeetingStatus();
		if (status == MEETING_STATUS_IDLE || status == MEETING_STATUS_ENDED || status == MEETING_STATUS_FAILED) {
			g_main_loop_quit(loop);
			return G_SOURCE_REMOVE;
		}
	}
	return TRUE;
}

//this catches a break signal, such as Ctrl + C
gboolean requestShutdown(gpointer)
{
	std::cout << "Shutdown requested." << std::endl;
	shutdown_requested = true;
	if (virtual_camera_source) virtual_camera_source->Stop();
	if (virtual_microphone_source) virtual_microphone_source->Stop();
	if (m_pMeetingService) LeaveMeeting();
	else if (loop) g_main_loop_quit(loop);
	return G_SOURCE_REMOVE;
}

void initAppSettings()
{
	g_unix_signal_add(SIGINT, requestShutdown, NULL);
	g_unix_signal_add(SIGTERM, requestShutdown, NULL);
}

std::string PlaybackState() {
	if (!playback_clock) return "idle";
	if (playback_clock->IsHalted()) return "stopped";
	if ((SendVideoRawData && virtual_camera_source && virtual_camera_source->HasFailed()) ||
		(SendAudioRawData && virtual_microphone_source && virtual_microphone_source->HasFailed())) return "failed";
	const bool finished = (!SendVideoRawData || (virtual_camera_source && virtual_camera_source->IsCompleted())) &&
		(!SendAudioRawData || (virtual_microphone_source && virtual_microphone_source->IsCompleted()));
	return finished ? "finished" : playback_clock->State();
}

void StopPlayback(bool mute = true) {
	if (playback_clock) playback_clock->Halt();
	if (virtual_camera_source) virtual_camera_source->Stop();
	if (virtual_microphone_source) virtual_microphone_source->Stop();
	if (mute && m_pMeetingService && m_pMeetingService->GetMeetingStatus() == MEETING_STATUS_INMEETING) {
		m_pMeetingService->GetMeetingVideoController()->MuteVideo();
		const auto myself = getMyself();
		if (myself) m_pMeetingService->GetMeetingAudioController()->MuteAudio(myself->GetUserID(), true);
	}
}

bool StartPlayback(const std::string& path, bool video, bool audio, std::string& error, bool image = false, double duration = 0) {
	if (shutdown_requested || !m_pMeetingService || m_pMeetingService->GetMeetingStatus() != MEETING_STATUS_INMEETING) {
		error = "BOT_NOT_ACTIVE"; return false;
	}
	const auto state = PlaybackState();
	if (state != "idle" && state != "finished" && state != "stopped" && state != "failed") {
		error = "PLAYBACK_ALREADY_ACTIVE"; return false;
	}
	if (!ValidateMedia(path, video, audio, error, image)) return false;
	StopPlayback(false);
	if (!video) m_pMeetingService->GetMeetingVideoController()->MuteVideo();
	if (!audio && getMyself()) m_pMeetingService->GetMeetingAudioController()->MuteAudio(getMyself()->GetUserID(), true);
	playback_clock = std::make_shared<PlaybackClock>(video, audio);
	DEFAULT_VIDEO_SOURCE = DEFAULT_AUDIO_SOURCE = path;
	SendVideoRawData = video; SendAudioRawData = audio;
	audio_started = false; audio_start_attempts = 0;
	music_audio_configured = false; music_audio_attempts = 0;
	SDKError result = SDKERR_SUCCESS;
	if (video) {
		if (virtual_camera_source) virtual_camera_source->SetMedia(path, playback_clock, image, duration);
		else {
			virtual_camera_source = new ZoomSDKVideoSource(path, playback_clock, image, duration);
		}
		if (!camera_registered) {
			const auto helper = GetRawdataVideoSourceHelper();
			result = helper ? helper->setExternalVideoSource(virtual_camera_source, FrameDataFormat_I420_LIMITED) : SDKERR_UNINITIALIZE;
			camera_registered = result == SDKERR_SUCCESS;
		}
		if (result == SDKERR_SUCCESS) result = m_pMeetingService->GetMeetingVideoController()->UnmuteVideo();
		if (result == SDKERR_SUCCESS && !virtual_camera_source->IsSending()) virtual_camera_source->onStartSend();
	}
	if (audio && result == SDKERR_SUCCESS) {
		if (virtual_microphone_source) virtual_microphone_source->SetMedia(path, playback_clock);
		else {
			virtual_microphone_source = new ZoomSDKVirtualAudioMicEvent(path, playback_clock, ConfigureMusicAudio);
		}
		if (!microphone_registered) {
			const auto helper = GetAudioRawdataHelper();
			result = helper ? helper->setExternalAudioSource(virtual_microphone_source) : SDKERR_UNINITIALIZE;
			microphone_registered = result == SDKERR_SUCCESS;
		}
		if (result == SDKERR_SUCCESS) {
			const auto myself = getMyself();
			if (myself && myself->GetAudioJoinType() != AUDIOTYPE_VOIP)
				m_pMeetingService->GetMeetingAudioController()->JoinVoip();
			result = myself ? m_pMeetingService->GetMeetingAudioController()->UnMuteAudio(myself->GetUserID()) : SDKERR_UNINITIALIZE;
			if (result == SDKERR_SUCCESS && !virtual_microphone_source->IsSending()) virtual_microphone_source->onMicStartSend();
		}
	}
	if (result != SDKERR_SUCCESS) {
		StopPlayback(); error = "SDK_MEDIA_START_FAILED:" + std::to_string(result); return false;
	}
	return true;
}

std::string ControlString(JsonObject* object, const char* key) {
	if (!json_object_has_member(object, key)) return "";
	auto node = json_object_get_member(object, key);
	if (!JSON_NODE_HOLDS_VALUE(node) || json_node_get_value_type(node) != G_TYPE_STRING) return "";
	return json_node_get_string(node);
}

JsonObject* HandleControl(JsonObject* request) {
	auto response = json_object_new();
	const auto operation = ControlString(request, "operation_id");
	const auto command = ControlString(request, "command");
	const auto playback = ControlString(request, "playback_id");
	std::string error;
	auto version = json_object_has_member(request, "version") ? json_object_get_member(request, "version") : nullptr;
	if (!version || !JSON_NODE_HOLDS_VALUE(version) || json_node_get_value_type(version) != G_TYPE_INT64 ||
		json_node_get_int(version) != 1 || operation.empty() || operation.size() > 128) error = "INVALID_REQUEST";
	else if (command == "status") {}
	else if (command == "play") {
		const auto type = ControlString(request, "media_type");
		const auto path = ControlString(request, "path");
		double duration = 0;
		bool validDuration = true;
		if (json_object_has_member(request, "duration_seconds")) {
			const auto node = json_object_get_member(request, "duration_seconds");
			if (!JSON_NODE_HOLDS_NULL(node)) {
				const auto valueType = json_node_get_value_type(node);
				if (type != "image" || (valueType != G_TYPE_DOUBLE && valueType != G_TYPE_INT64)) validDuration = false;
				else { duration = json_node_get_double(node); validDuration = std::isfinite(duration) && duration >= 1 && duration <= 3600; }
			}
		}
		if (playback.empty() || playback.size() > 128 || path.empty() || path[0] != '/') error = "INVALID_REQUEST";
		else if (!validDuration) error = "INVALID_DURATION";
		else if (type != "video" && type != "video-silent" && type != "audio" && type != "image") error = "MEDIA_TYPE_UNSUPPORTED";
		else if (StartPlayback(path, type != "audio", type == "video" || type == "audio", error, type == "image", duration)) current_playback_id = playback;
	}
	else if (command == "quit") requestShutdown(nullptr);
	else if (command != "pause" && command != "resume" && command != "stop") error = "UNKNOWN_COMMAND";
	else if (playback.empty() || playback != current_playback_id) error = "PLAYBACK_ID_MISMATCH";
	else if (!playback_clock) error = "PLAYBACK_NOT_READY";
	else if (command == "stop") StopPlayback();
	else if (PlaybackState() == "finished" || PlaybackState() == "stopped") error = "PLAYBACK_NOT_ACTIVE";
	else if (command == "pause") playback_clock->Pause();
	else if (command == "resume") playback_clock->Resume();
	json_object_set_int_member(response, "version", 1);
	json_object_set_string_member(response, "operation_id", operation.c_str());
	json_object_set_boolean_member(response, "ok", error.empty());
	if (!error.empty()) json_object_set_string_member(response, "error", error.c_str());
	json_object_set_string_member(response, "playback_id", current_playback_id.c_str());
	json_object_set_string_member(response, "playback_state", PlaybackState().c_str());
	double position = 0;
	if (SendVideoRawData && virtual_camera_source) position = virtual_camera_source->Position();
	if (SendAudioRawData && virtual_microphone_source) position = SendVideoRawData ? std::min(position, virtual_microphone_source->Position()) : virtual_microphone_source->Position();
	json_object_set_double_member(response, "position_seconds", position);
	json_object_set_int_member(response, "video_frames_sent", SendVideoRawData && virtual_camera_source ? virtual_camera_source->AcceptedFrames() : 0);
	json_object_set_int_member(response, "audio_blocks_sent", SendAudioRawData && virtual_microphone_source ? virtual_microphone_source->AcceptedBlocks() : 0);
	json_object_set_int_member(response, "meeting_status", m_pMeetingService ? m_pMeetingService->GetMeetingStatus() : MEETING_STATUS_IDLE);
	json_object_set_boolean_member(response, "in_meeting", m_pMeetingService && m_pMeetingService->GetMeetingStatus() == MEETING_STATUS_INMEETING);
	json_object_set_boolean_member(response, "shutdown_requested", shutdown_requested);
	return response;
}

gboolean onPlaybackCommand(gint fd, GIOCondition condition, gpointer) {
	char buffer[256];
	ssize_t count;
	while ((count = read(fd, buffer, sizeof(buffer))) > 0) playback_control_buffer.append(buffer, count);
	if (playback_control_buffer.size() > 1024) { playback_control_buffer.clear(); std::cerr << "Playback command too long." << std::endl; return G_SOURCE_CONTINUE; }
	size_t newline;
	while ((newline = playback_control_buffer.find('\n')) != std::string::npos) {
		std::string command = playback_control_buffer.substr(0, newline);
		playback_control_buffer.erase(0, newline + 1);
		if (!command.empty() && command.back() == '\r') command.pop_back();
		if (command == "quit") { requestShutdown(nullptr); return G_SOURCE_REMOVE; }
		if (command.compare(0, 5, "play ") == 0) {
			const auto separator = command.find(' ', 5);
			const auto type = command.substr(5, separator == std::string::npos ? separator : separator - 5);
			std::string error;
			if (separator == std::string::npos || (type != "video" && type != "video-silent" && type != "audio"))
				std::cerr << "Use play video|video-silent|audio /absolute/file." << std::endl;
			else if (!StartPlayback(command.substr(separator + 1), type != "audio", type != "video-silent", error))
				std::cerr << "Playback rejected: " << error << std::endl;
			else std::cout << "Playback requested; state: " << PlaybackState() << std::endl;
			continue;
		}
		if (!playback_clock) { std::cout << "Playback is not ready." << std::endl; continue; }
		if (command == "pause") { playback_clock->Pause(); std::cout << "Playback state: " << playback_clock->State() << std::endl; }
		else if (command == "resume") { playback_clock->Resume(); std::cout << "Playback state: " << playback_clock->State() << std::endl; }
		else if (command == "stop") {
			StopPlayback();
			std::cout << "Playback stopped; participant remains in meeting." << std::endl;
		}
		else if (command == "status") {
			const bool finished = (!SendVideoRawData || (virtual_camera_source && virtual_camera_source->IsCompleted())) &&
				(!SendAudioRawData || (virtual_microphone_source && virtual_microphone_source->IsCompleted()));
			std::cout << "Playback state: " << (playback_clock->IsHalted() ? "stopped" : finished ? "finished" : playback_clock->State()) << std::endl;
		}
		else std::cout << "Unknown playback command. Use pause, resume, stop, status or quit." << std::endl;
	}
	return G_SOURCE_CONTINUE;
}

void initPlaybackControl() {
	if (mkfifo(playback_control_path, 0600) != 0 && errno != EEXIST) { std::cerr << "Cannot create playback command pipe." << std::endl; return; }
	struct stat info;
	if (lstat(playback_control_path, &info) != 0 || !S_ISFIFO(info.st_mode)) { std::cerr << "Playback command path is not a FIFO." << std::endl; return; }
	playback_control_fd = open(playback_control_path, O_RDWR | O_NONBLOCK | O_CLOEXEC);
	if (playback_control_fd < 0) { std::cerr << "Cannot open playback command pipe." << std::endl; return; }
	g_unix_fd_add(playback_control_fd, G_IO_IN, onPlaybackCommand, nullptr);
	std::cout << "Playback commands ready: pause, resume, stop, status, quit." << std::endl;
}

int main(int argc, char* argv[])
{

	ReadTEXTSettings();
	if (SendVideoRawData || SendAudioRawData) {
		std::string error;
		if (!ValidateMedia(DEFAULT_VIDEO_SOURCE, SendVideoRawData, SendAudioRawData, error)) {
			std::cerr << error << std::endl;
			return 1;
		}
	}
	setvbuf(stdout, NULL, _IONBF, 0);
	loop = g_main_loop_new(NULL, FALSE);

	

	InitMeetingSDK();
	if (app_exit_code) { g_main_loop_unref(loop); return app_exit_code; }
	AuthMeetingSDK();
	initAppSettings();
	initPlaybackControl();
	SdkControlServer control_server("/tmp/zoom-sdk-control.sock", HandleControl);
	if (!control_server.Start()) {
		std::cerr << "Cannot start private SDK control socket." << std::endl;
		app_exit_code = 1;
		requestShutdown(nullptr);
	}



	// add source to default context
	g_timeout_add(1000, timeout_callback, loop);
	if (!app_exit_code) g_main_loop_run(loop);
	if (virtual_camera_source) virtual_camera_source->Stop();
	if (virtual_microphone_source) virtual_microphone_source->Stop();
	CleanSDK();
	delete virtual_camera_source;
	delete virtual_microphone_source;
	g_main_loop_unref(loop);
	if (playback_control_fd >= 0) { close(playback_control_fd); unlink(playback_control_path); }
	std::cout << "SDK cleaned up. Exiting." << std::endl;
	return app_exit_code;
}
