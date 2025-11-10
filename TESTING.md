# Testing Guide for NDN-gRPC Bridge

## Prerequisites

1. **NFD (NDN Forwarding Daemon) must be running**
   ```bash
   # Check if NFD is running
   nfd-status
   
   # If not running, start it
   nfd-start
   ```

2. **Update config.yaml**
   - Set `grpc.bridge_enabled: true` to enable NDN-to-gRPC bridge

## Testing Steps

### Option 1: Manual Testing (Recommended)

**Terminal 1: Start gRPC Server (with NDN enabled)**
```bash
cd /Users/yaoqingqi/Yao/github/Python-Convert
source venv/bin/activate
python -m python_project.grpc server --enable-ndn
```

**Terminal 2: Start NDN Server (with gRPC bridge enabled)**
```bash
cd /Users/yaoqingqi/Yao/github/Python-Convert
source venv/bin/activate
python -m python_project server
```

**Terminal 3: Test with gRPC Client**
```bash
cd /Users/yaoqingqi/Yao/github/Python-Convert
source venv/bin/activate
python -m python_project.grpc client
```

### Option 2: Test Flow

1. **gRPC Client → gRPC Server → NDN Network → NDN Server → gRPC Server → gRPC Client**
   - gRPC client sends request
   - gRPC server converts to Interest and sends to NDN
   - NDN server receives Interest, converts to gRPC request, calls gRPC server
   - gRPC server processes and returns response
   - NDN server converts response to Data packet
   - gRPC server receives Data, converts to response, returns to client

2. **Expected Result:**
   - gRPC client should receive responses with processed data
   - Check logs in all terminals to see the conversion flow

## Configuration

Make sure `config.yaml` has:
```yaml
grpc:
  bridge_enabled: true  # Enable NDN-to-gRPC bridge
```

## Troubleshooting

1. **"No Route" error**: Make sure NFD is running and routes are registered
2. **Connection refused**: Check if both servers are running
3. **Import errors**: Make sure virtual environment is activated

