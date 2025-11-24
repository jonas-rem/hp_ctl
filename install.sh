#!/bin/bash
set -e

# Configuration
SERVICE_NAME="hp-ctl"
SERVICE_FILE="hp-ctl.service"
INSTALL_DIR="/opt/hp-ctl"
CONFIG_FILE="config.yaml"
SERVICE_USER="hpctl"
SERVICE_GROUP="hpctl"

echo "HP Control Installation Script"
echo "================================"
echo

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Error: This script must be run as root (use sudo)"
    exit 1
fi

# Check if systemd is available
if ! command -v systemctl &> /dev/null; then
    echo "Error: systemd is not available on this system"
    exit 1
fi

# Check if config file exists in project
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Configuration file $CONFIG_FILE not found in project directory"
    exit 1
fi

# Stop existing service if running
if systemctl is-active --quiet $SERVICE_NAME; then
    echo "Stopping existing $SERVICE_NAME service..."
    systemctl stop $SERVICE_NAME
fi

# Create service user and group if they don't exist
if ! id -u $SERVICE_USER &> /dev/null; then
    echo "Creating service user: $SERVICE_USER"
    useradd --system --no-create-home --shell /bin/false $SERVICE_USER
else
    echo "Service user $SERVICE_USER already exists"
fi

# Create installation directory
echo "Creating installation directory: $INSTALL_DIR"
mkdir -p $INSTALL_DIR

# Build and install the package
echo "Building and installing hp-ctl package..."
python3 -m pip install --break-system-packages .

# Copy configuration file
echo "Copying configuration file to $INSTALL_DIR"
cp $CONFIG_FILE $INSTALL_DIR/

# Set ownership and permissions
echo "Setting ownership and permissions"
chown -R $SERVICE_USER:$SERVICE_GROUP $INSTALL_DIR
chmod 755 $INSTALL_DIR
chmod 644 $INSTALL_DIR/$CONFIG_FILE

# Install systemd service
echo "Installing systemd service"
if [ ! -f "$SERVICE_FILE" ]; then
    echo "Error: Service file $SERVICE_FILE not found"
    exit 1
fi

cp $SERVICE_FILE /etc/systemd/system/
chmod 644 /etc/systemd/system/$SERVICE_FILE

# Reload systemd daemon
echo "Reloading systemd daemon"
systemctl daemon-reload

# Enable service to start on boot
echo "Enabling $SERVICE_NAME service"
systemctl enable $SERVICE_NAME

echo
echo "Installation completed successfully!"
echo
echo "Next steps:"
echo "1. Add hpctl user to dialout group: sudo usermod -a -G dialout hpctl"
echo "2. Edit configuration: sudo nano $INSTALL_DIR/$CONFIG_FILE"
echo "3. Start the service: sudo systemctl start $SERVICE_NAME"
echo "4. Check status: sudo systemctl status $SERVICE_NAME"
echo "5. View logs: sudo journalctl -u $SERVICE_NAME -f"
