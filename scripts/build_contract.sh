#!/bin/bash

# Build the flash loan contract
echo "Building flash loan contract..."
anchor build

# Copy IDL to Python directory for easier access
if [ -f "target/idl/flash_loan.json" ]; then
    cp target/idl/flash_loan.json src/ingest/
    echo "IDL copied to src/ingest/"
fi

echo "Build complete. Deploy with: anchor deploy"