#include "BotVideoEvents.h"
#include <cassert>
using namespace ZOOMSDK;
struct Request : IRequestStartVideoHandler {
    int accepted = 0, cancelled = 0;
    unsigned int GetReqFromUserId() override { return 1; }
    SDKError Ignore() override { assert(false); return SDKERR_SUCCESS; }
    SDKError Accept() override { ++accepted; return SDKERR_SUCCESS; }
    SDKError Cancel() override { ++cancelled; return SDKERR_SUCCESS; }
};
int main() {
    bool desired = false;
    BotVideoEvents events([&] { return desired; }, [] { return 2u; });
    Request idle;
    events.onHostRequestStartVideo(&idle);
    assert(idle.cancelled == 1 && idle.accepted == 0);
    desired = true;
    Request active;
    events.onHostRequestStartVideo(&active);
    assert(active.accepted == 1 && active.cancelled == 0);
    desired = false; // stop, EOF, audio-only or leaving: never activate camera.
    Request stopped;
    events.onHostRequestStartVideo(&stopped);
    assert(stopped.cancelled == 1 && stopped.accepted == 0);
    events.onHostRequestStartVideo(nullptr);
}
