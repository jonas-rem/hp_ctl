#!/bin/bash
set -e

# Configuration
SERVICE_NAME="hp-ctl"
SERVICE_FILE="hp-ctl.service"
CONFIG_FILE="config.yaml"
UDEV_RULES_FILE="99-usb-serial.rules"
USER_SERVICE_DIR="$HOME/.config/systemd/user"
USER_CONFIG_DIR="$HOME/.config/hp-ctl"


echo "HP Control Installation Script"
echo "================================"
echo

# Check if systemd is available
if ! command -v systemctl &> /dev/null; then
    echo "Error: systemd is not available on this system"
    exit 1
fi

# Check if config file exists
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Configuration file $CONFIG_FILE not found"
    exit 1
fi

# Check if service file exists
if [ ! -f "$SERVICE_FILE" ]; then
    echo "Error: Service file $SERVICE_FILE not found"
    exit 1
fi

# Check if udev rules file exists
if [ ! -f "$UDEV_RULES_FILE" ]; then
    echo "Error: udev rules file $UDEV_RULES_FILE not found"
    exit 1
fi

# Stop existing service if running
if systemctl --user is-active --quiet $SERVICE_NAME 2>/dev/null; then
    echo "Stopping existing $SERVICE_NAME service..."
    systemctl --user stop $SERVICE_NAME
fi

# Create user service directory
echo "Creating user service directory: $USER_SERVICE_DIR"
mkdir -p $USER_SERVICE_DIR

# Create user configuration directory
echo "Creating configuration directory: $USER_CONFIG_DIR"
mkdir -p $USER_CONFIG_DIR

# Build and install the package for current user
echo "Building and installing hp-ctl package..."
pip3 install --user . --break-system-packages

# Copy configuration file
echo "Copying configuration file to $USER_CONFIG_DIR"
cp $CONFIG_FILE $USER_CONFIG_DIR/

# Install udev rules for USB serial device
echo "Installing udev rules..."
sudo cp $UDEV_RULES_FILE /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger

# Install systemd user service
echo "Installing systemd user service"
cp "$SERVICE_FILE" "$USER_SERVICE_DIR/$SERVICE_FILE"

# Reload systemd user daemon
echo "Reloading systemd user daemon"
systemctl --user daemon-reload

# Enable service to start on login
echo "Enabling $SERVICE_NAME service"
systemctl --user enable $SERVICE_NAME

# Enable linger so service runs even when not logged in
echo "Enabling linger for user $USER"
loginctl enable-linger $USER

echo
echo "Installation completed successfully!"
echo
echo "Next steps:"
echo "1. Replug your USB serial device (or reboot)"
echo "2. Edit config: vim $USER_CONFIG_DIR/$CONFIG_FILE"
echo "3. Start service: systemctl --user start $SERVICE_NAME"
echo "4. Check status: systemctl --user status $SERVICE_NAME"
echo "5. View logs: journalctl --user -u $SERVICE_NAME -f"
echo
echo "Device will be available at: /dev/ttyUSB_custom"
