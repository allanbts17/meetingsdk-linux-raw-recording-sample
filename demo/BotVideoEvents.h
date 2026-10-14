#pragma once
#include "meeting_service_components/meeting_video_interface.h"
#include <functional>
#include <iostream>

// The SDK request handler destroys itself in Accept/Cancel; never retain it.
class BotVideoEvents : public ZOOMSDK::IMeetingVideoCtrlEvent {
public:
    BotVideoEvents(std::function<bool()> desired, std::function<unsigned int()> self)
        : desired_(std::move(desired)), self_(std::move(self)) {}
    void onUserVideoStatusChange(unsigned int user, ZOOMSDK::VideoStatus status) override {
        if (user == self_()) std::cout << "Self video status: " << status << std::endl;
    }
    void onHostRequestStartVideo(ZOOMSDK::IRequestStartVideoHandler* handler) override {
        if (!handler) return;
        const bool accept = desired_();
        const auto result = accept ? handler->Accept() : handler->Cancel();
        std::cout << "Host video request " << (accept ? "accepted" : "cancelled")
                  << ", SDK result: " << result << std::endl;
    }
    void onSpotlightedUserListChangeNotification(ZOOMSDK::IList<unsigned int>*) override {}
    void onActiveSpeakerVideoUserChanged(unsigned int) override {}
    void onActiveVideoUserChanged(unsigned int) override {}
    void onHostVideoOrderUpdated(ZOOMSDK::IList<unsigned int>*) override {}
    void onLocalVideoOrderUpdated(ZOOMSDK::IList<unsigned int>*) override {}
    void onFollowHostVideoOrderChanged(bool) override {}
    void onUserVideoQualityChanged(ZOOMSDK::VideoConnectionQuality, unsigned int) override {}
    void onVideoAlphaChannelStatusChanged(bool) override {}
    void onCameraControlRequestReceived(unsigned int, ZOOMSDK::CameraControlRequestType,
                                       ZOOMSDK::ICameraControlRequestHandler* handler) override {
        if (handler) handler->Decline();
    }
    void onCameraControlRequestResult(unsigned int, ZOOMSDK::CameraControlRequestResult) override {}
private:
    std::function<bool()> desired_;
    std::function<unsigned int()> self_;
};
