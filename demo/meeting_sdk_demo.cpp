#include <limits.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>
#include <glib.h>
#include <sstream>
#include <thread>
#include <sys/syscall.h>
#include <sys/syscall.h>
#include <fstream>
#include <iosfwd>
#include <iostream>
#include <map>
#include <algorithm>

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
std::string DEFAULT_AUDIO_SOURCE = "yourwavefile.wav";

//references for SendVideoRawData
std::string DEFAULT_VIDEO_SOURCE = "yourmp4file.mp4";


GMainLoop* loop;


//These are needed to readsettingsfromTEXT named config.txt
std::string meeting_number, token, meeting_password, recording_token,onBehalfOf_Token;


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

//check if you meet the requirements to send raw data
void CheckAndStartRawSending(bool isVideo, bool isAudio) {


	//SendVideoRawData
	if (isVideo) {

		ZoomSDKVideoSource* virtual_camera_video_source = new ZoomSDKVideoSource(DEFAULT_VIDEO_SOURCE);
		IZoomSDKVideoSourceHelper* p_videoSourceHelper = GetRawdataVideoSourceHelper();

		if (p_videoSourceHelper) {
			SDKError err = p_videoSourceHelper->setExternalVideoSource(virtual_camera_video_source);



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
		ZoomSDKVirtualAudioMicEvent* audio_source = new ZoomSDKVirtualAudioMicEvent(DEFAULT_AUDIO_SOURCE);
		IZoomSDKAudioRawDataHelper* audioHelper = GetAudioRawdataHelper();
		if (audioHelper) {
			SDKError err = audioHelper->setExternalAudioSource(audio_source);
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
	// CleanSDK();
	//std::exit(0);
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
	}
	else{

		std::cerr << "Readfile success." << std::endl;
	}

	std::map<std::string, std::string> config;
	std::string line;

	while (std::getline(configFile, line)) {
		// Process each line to extract key-value pairs
		processLine(line, config);
		
		std::cerr << "Reading.." << line <<std::endl;
	}

	// Example: Accessing values by key
	if (config.find("meeting_number") != config.end()) {
		
		meeting_number=config["meeting_number"];
		std::cout << "Meeting Number: " << config["meeting_number"] << std::endl;
	}
	if (config.find("token") != config.end()) {
		 token=config["token"];
		 	std::cout << "Token: " << token<< std::endl;
	}
	if (config.find("meeting_password") != config.end()) {
		
		meeting_password=config["meeting_password"];
		std::cout << "meeting_password: " << meeting_password << std::endl;
	}
	if (config.find("recording_token") != config.end()) {
	
		 recording_token=config["recording_token"];
		 	std::cout << "recording_token: " << recording_token << std::endl;
	}
	if (config.find("onBehalfOf_Token") != config.end()) {
	
		 onBehalfOf_Token=config["onBehalfOf_Token"];
		 	std::cout << "onBehalfOf_Token: " << onBehalfOf_Token << std::endl;
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

	// Additional processing or handling of parsed values can be done here

	printf("directory of config file: %s\n", self_dir.c_str());


}


void CleanSDK()
{
	ZOOM_SDK_NAMESPACE::SDKError err(ZOOM_SDK_NAMESPACE::SDKERR_SUCCESS);

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
	if (m_pMeetingService)
	{
		ZOOM_SDK_NAMESPACE::DestroyMeetingService(m_pMeetingService);
		m_pMeetingService = NULL;
	}
	if (videoHelper) {
		videoHelper->unSubscribe();
	}
	if (audioHelper) {
		audioHelper->unSubscribe();
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
	if ((err2 = CreateMeetingService(&m_pMeetingService)) != SDKError::SDKERR_SUCCESS) {};
	std::cerr << "MeetingService created." << std::endl;

	//before joining a meeting, create the setting service
	//this object is used to for settings
	CreateSettingService(&m_pSettingService);
	std::cerr << "Settingservice created." << std::endl;

	// Set the event listener for meeting status
	m_pMeetingService->SetEvent(new MeetingServiceEventListener(&onMeetingJoined, &onMeetingEndsQuitApp, &onInMeeting));

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
	ZOOM_SDK_NAMESPACE::JoinParam joinParam;
	ZOOM_SDK_NAMESPACE::SDKError err(ZOOM_SDK_NAMESPACE::SDKERR_SERVICE_FAILED);
	joinParam.userType = ZOOM_SDK_NAMESPACE::SDK_UT_WITHOUT_LOGIN;
	ZOOM_SDK_NAMESPACE::JoinParam4WithoutLogin& withoutloginParam = joinParam.param.withoutloginuserJoin;
	// withoutloginParam.meetingNumber = 1231231234;
	withoutloginParam.meetingNumber = std::stoull(meeting_number);
	withoutloginParam.vanityID = NULL;
	withoutloginParam.userName = "LinuxChun";
	// withoutloginParam.psw = "1";
	withoutloginParam.psw = meeting_password.c_str();
	withoutloginParam.customer_key = NULL;
	withoutloginParam.webinarToken = NULL;
	withoutloginParam.isVideoOff = false;
	withoutloginParam.isAudioOff = false;

	std::cerr << "JWT token is " << token << std::endl;
	std::cerr << "Recording token is " << recording_token << std::endl;

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
	
	std::cerr << "onBehalfOf Token is " << onBehalfOf_Token << std::endl;
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
			pAudioContext->EnableAlwaysMuteMicWhenJoinVoip(true);
			pAudioContext->SetSuppressBackgroundNoiseLevel(Suppress_BGNoise_Level_None);

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
	if ((err = CreateAuthService(&m_pAuthService)) != SDKError::SDKERR_SUCCESS) {};
	std::cerr << "AuthService created." << std::endl;

	//Create a param to insert jwt token
	ZOOM_SDK_NAMESPACE::AuthContext param;

	//set the event listener for onauthenticationcompleted
	if ((err = m_pAuthService->SetEvent(new AuthServiceEventListener(&OnAuthenticationComplete))) != SDKError::SDKERR_SUCCESS) {};
	std::cout << "AuthServiceEventListener added." << std::endl;


	if (!token.size() == 0){
		param.jwt_token = token.c_str();
		std::cerr << "AuthSDK:token extracted from config file " <<param.jwt_token  << std::endl;
	}
	m_pAuthService->SDKAuth(param);
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
	ZOOM_SDK_NAMESPACE::InitParam initParam;

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
	return TRUE;
}

//this catches a break signal, such as Ctrl + C
void my_handler(int s)
{
	printf("\nCaught signal %d\n", s);
	LeaveMeeting();
	printf("Leaving session.\n");
	CleanSDK();

	

	//InitMeetingSDK();
	//AuthMeetingSDK();

	std::exit(0);
}

void initAppSettings()
{
	struct sigaction sigIntHandler;
	sigIntHandler.sa_handler = my_handler;
	sigemptyset(&sigIntHandler.sa_mask);
	sigIntHandler.sa_flags = 0;
	sigaction(SIGINT, &sigIntHandler, NULL);
}

int main(int argc, char* argv[])
{

	ReadTEXTSettings();

	

	InitMeetingSDK();
	AuthMeetingSDK();
	initAppSettings();



	loop = g_main_loop_new(NULL, FALSE);
	// add source to default context
	g_timeout_add(1000, timeout_callback, loop);
	g_main_loop_run(loop);
	return 0;
}
