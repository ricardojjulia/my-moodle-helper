#!/bin/bash
# Start both backend and frontend dev servers

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# Kill anything already on these ports
lsof -ti:4100 | xargs kill -9 2>/dev/null
lsof -ti:4101 | xargs kill -9 2>/dev/null
sleep 1

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Moodle Course Creator"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Start backend, log to /tmp/backend.log
uvicorn app.backend.main:app --reload --host 127.0.0.1 --port 4100 \
  > /tmp/moodle_backend.log 2>&1 &
BACKEND_PID=$!

# Wait for backend to be ready
echo -n "  Starting backend"
for i in $(seq 1 15); do
  sleep 1
  if curl -s -o /dev/null http://127.0.0.1:4100/api/settings; then
    echo " ✓"
    break
  fi
  echo -n "."
done

# Start frontend
cd "$ROOT/app/frontend"
npm run dev > /tmp/moodle_frontend.log 2>&1 &
FRONTEND_PID=$!

# Wait for frontend to be ready
echo -n "  Starting frontend"
for i in $(seq 1 15); do
  sleep 1
  if curl -s -o /dev/null http://127.0.0.1:4101/; then
    echo " ✓"
    break
  fi
  echo -n "."
done

echo ""
echo "  ✓ Backend  → http://localhost:4100"
echo "  ✓ Frontend → http://localhost:4101"
echo "  ✓ API docs → http://localhost:4100/docs"
echo ""

# Open browser
open "http://localhost:4101" 2>/dev/null || true

echo "  Logs: /tmp/moodle_backend.log  /tmp/moodle_frontend.log"
echo "  Press Ctrl+C to stop."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; echo 'Stopped.'; exit" INT TERM
wait
