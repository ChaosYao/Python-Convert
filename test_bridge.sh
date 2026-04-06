#!/bin/bash
# Test script for NDN-gRPC bridge
# This script starts both NDN server and gRPC server in separate terminals

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Starting NDN-gRPC Bridge Test${NC}"
echo ""

# Check if config.yaml exists
if [ ! -f "config.yaml" ]; then
    echo -e "${YELLOW}Warning: config.yaml not found${NC}"
    exit 1
fi

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

echo -e "${BLUE}Step 1: Starting gRPC Server (with NDN enabled)${NC}"
echo "Run this command in Terminal 1:"
echo -e "${GREEN}python -m python_project.grpc server --enable-ndn${NC}"
echo ""

echo -e "${BLUE}Step 2: Starting NDN Server (with gRPC bridge enabled)${NC}"
echo "First, update config.yaml: set bridge_enabled: true"
echo "Then run this command in Terminal 2:"
echo -e "${GREEN}python -m python_project server${NC}"
echo ""

echo -e "${BLUE}Step 3: Test with gRPC Client${NC}"
echo "Run this command in Terminal 3:"
echo -e "${GREEN}python -m python_project.grpc client${NC}"
echo ""

echo -e "${YELLOW}Note: Make sure NFD (NDN Forwarding Daemon) is running!${NC}"
echo "Check with: nfd-status"
echo "Start with: nfd-start"

