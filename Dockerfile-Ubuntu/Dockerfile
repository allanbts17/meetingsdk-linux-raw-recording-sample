# Use the official Ubuntu image as the base image
FROM ubuntu:22.04

# Install necessary dependencies
RUN apt-get update && \
    apt-get install -y build-essential cmake

RUN apt-get install -y pkgconf


RUN apt-get update && apt-get install -y --no-install-recommends --no-install-suggests \
    libgl1-mesa-glx \
    libxkbcommon-x11-0 \
    libxcb-icccm4 \
    libxcb-render-util0 \
    libxcb-xinerama0 \
    libfontconfig1 \
    libx11-xcb1 \
    libxcb-xfixes0 \
    libxcb-shape0 \
    libxcb-shm0 \
    libxcb-randr0 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-xtest0 \
    libdbus-1-3 \
    libglib2.0-0 \
    libgbm1 \
    libxfixes3 \
    libgl1 \
    libdrm2 \
    libgssapi-krb5-2 \
    openssl \
    ca-certificates \
    pkg-config \
    libegl-mesa0 \
    libsdl2-dev \
    libudev1 \
    g++-multilib


# Install CURL related libs
RUN apt-get install -y libcurl4-openssl-dev

# Install ALSA
RUN apt-get install -y libasound2 libasound2-plugins alsa alsa-utils alsa-oss

# Install Pulseaudio
RUN apt-get install -y  pulseaudio pulseaudio-utils



# Set the working directory
WORKDIR /app

# Copy your application files to the container
COPY demo/ /app/demo/

# Fix Windows line endings and permissions
RUN apt-get update && apt-get install -y dos2unix pciutils xvfb && \
    dos2unix /app/demo/*.sh && \
    chmod +x /app/demo/*.sh

# Execute additional commands
# RUN cd /app/demo && \
#     mkdir -p lib/zoom_meeting_sdk && \
#     cd /app/demo && \
#     rm -rf build && cmake -B build && cd build && make
RUN cd /app/demo/lib/zoom_meeting_sdk && \
    ln -sf libmeetingsdk.so libmeetingsdk.so.1 && \
    cd /app/demo && \
    rm -rf build && cmake -B build && cd build && make


# Set the working directory to the source folder
WORKDIR /app/demo/bin

# Set the working directory to the binary folder
WORKDIR /app/demo/bin


# Define a shell script to run multiple commands
RUN echo '#!/bin/bash' > /app/demo/run.sh \
    && echo 'source /app/demo/setup-pulseaudio.sh' >> /app/demo/run.sh \
    && echo 'xvfb-run -a -s "-screen 0 1920x1080x24" ./meetingSDKDemo' >> /app/demo/run.sh \
    && echo 'echo "===== ZOOM SDK LOGS ====="' >> /app/demo/run.sh \
    && echo 'cat ~/.zoomsdk/logs/*.log || true' >> /app/demo/run.sh



# Make the run script executable
RUN dos2unix /app/demo/run.sh && chmod +x /app/demo/run.sh

# Specify the run script as the CMD
CMD ["/app/demo/run.sh"]

#CMD ["/bin/bash"]
#CMD ["./meetingSDKDemo"]