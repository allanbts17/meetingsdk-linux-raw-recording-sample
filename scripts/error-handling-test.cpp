#include "MediaValidation.h"
#include "AuthServiceEventListener.h"
#include "MeetingServiceEventListener.h"
#include <cassert>
#include <iostream>
using namespace ZOOMSDK;
int failures = 0, lastFailure = 0, successes = 0;
void failed(int code) { ++failures; lastFailure = code; }
void succeeded() { ++successes; }
int main() {
    std::string error;
    assert(ValidateMedia("/tmp/av-test.mkv", true, true, error));
    assert(!ValidateMedia("/tmp/missing.mp4", true, true, error));
    assert(error.find("missing") != std::string::npos);
    assert(!ValidateMedia("/tmp/invalid.mp4", true, true, error));
    assert(error.find("Invalid") != std::string::npos);
    assert(!ValidateMedia("/tmp/video-only.mp4", true, true, error));
    assert(error.find("lacks") != std::string::npos);
    assert(ValidateMedia("/tmp/video-only.mp4", true, false, error));
    AuthServiceEventListener auth(succeeded, failed);
    auth.onAuthenticationReturn(AUTHRET_JWTTOKENWRONG);
    assert(failures == 1 && lastFailure == AUTHRET_JWTTOKENWRONG);
    auth.onAuthenticationReturn(AUTHRET_SUCCESS);
    assert(successes == 1 && failures == 1);
    MeetingServiceEventListener meeting(nullptr, nullptr, succeeded, failed);
    for (const auto code : {MEETING_FAIL_PASSWORD_ERR, MEETING_FAIL_MEETING_NOT_EXIST, MEETING_FAIL_CANNOT_START_TOKENEXPIRE}) {
        meeting.onMeetingStatusChanged(MEETING_STATUS_FAILED, code);
        assert(lastFailure == code);
    }
    assert(failures == 4);
    meeting.onMeetingStatusChanged(MEETING_STATUS_INMEETING, 0);
    assert(successes == 2 && failures == 4);
    std::cout << "Error tests passed: media preflight, auth failure/success and meeting failure callbacks." << std::endl;
}
