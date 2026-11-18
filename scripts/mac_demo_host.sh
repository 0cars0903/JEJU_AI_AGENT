#!/bin/zsh
# Vercel 데모용 Mac mini Ollama 상시 가동(2026-11-18, 문제 기록 69번).
# 구성: Vercel 함수 → Tailscale Funnel(https://<기기>.<tailnet>.ts.net) → ollama_gate(127.0.0.1:11500, 공유 토큰 검사) → Ollama(127.0.0.1:11436)
# 사용: zsh scripts/mac_demo_host.sh install | status | token | uninstall
#  - install: ~/.jeju에 프록시를 복사하고 토큰을 만든 뒤(이미 있으면 그대로) 두 서비스를 launchd에 올린다. 로그인하면 자동 시작, 죽으면 다시 뜬다.
#  - token: 토큰을 클립보드로 복사한다(화면에 찍지 않음). Vercel 환경 변수 OLLAMA_TOKEN에 붙여 넣는다.
# 외장 디스크가 늦게 붙어도 돌도록 실행 파일은 모두 홈 폴더(~/.jeju)에 둔다.
set -e
CMD=${1:-status}
J=$HOME/.jeju
LA=$HOME/Library/LaunchAgents
OLLAMA=/Applications/Ollama.app/Contents/Resources/ollama
HERE=${0:A:h}
U=gui/$(id -u)

plist() {  # $1 이름, $2 프로그램 인자(XML string 줄), $3 환경 변수(XML key/string 줄)
  cat > $LA/$1.plist <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$1</string>
  <key>ProgramArguments</key><array>$2</array>
  <key>EnvironmentVariables</key><dict>$3</dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardErrorPath</key><string>$J/$1.log</string>
  <key>StandardOutPath</key><string>$J/$1.log</string>
</dict></plist>
EOF
}

case $CMD in
install)
  mkdir -p $J && chmod 700 $J
  cp "$HERE/ollama_gate.py" $J/ollama_gate.py
  if [[ ! -s $J/ollama_token ]]; then
    /usr/bin/python3 -c "import secrets;print(secrets.token_urlsafe(32))" > $J/ollama_token
  fi
  chmod 600 $J/ollama_token
  plist com.jeju.ollama "<string>$OLLAMA</string><string>serve</string>" \
    "<key>OLLAMA_HOST</key><string>127.0.0.1:11436</string><key>OLLAMA_MODELS</key><string>$HOME/.ollama/models</string><key>OLLAMA_KEEP_ALIVE</key><string>24h</string>"
  plist com.jeju.ollama-gate "<string>/usr/bin/python3</string><string>$J/ollama_gate.py</string>" \
    "<key>JEJU_GATE_TOKEN_FILE</key><string>$J/ollama_token</string><key>JEJU_GATE_PORT</key><string>11500</string><key>JEJU_GATE_UPSTREAM</key><string>http://127.0.0.1:11436</string>"
  for n in com.jeju.ollama com.jeju.ollama-gate; do
    launchctl bootout $U/$n 2>/dev/null || true
    launchctl bootstrap $U $LA/$n.plist
  done
  echo "설치함. 상태: zsh scripts/mac_demo_host.sh status"
  ;;
status)
  for n in com.jeju.ollama com.jeju.ollama-gate; do launchctl print $U/$n 2>/dev/null | grep -E '^\s+(state|pid) =' | tr -s ' ' | sed "s/^/$n /" || echo "$n 없음"; done
  T=$(cat $J/ollama_token 2>/dev/null || true)
  echo "Ollama 11436: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:11436/api/tags)"
  echo "gate 11500(토큰 없음, 401이면 정상): $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:11500/api/tags)"
  echo "gate 11500(토큰 있음, 200이면 정상): $(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $T" http://127.0.0.1:11500/api/tags)"
  command -v tailscale >/dev/null && tailscale funnel status || echo "tailscale 명령 없음"
  ;;
token)
  pbcopy < $J/ollama_token && echo "토큰을 클립보드에 복사함(길이 $(wc -c < $J/ollama_token | tr -d ' ')자)"
  ;;
uninstall)
  for n in com.jeju.ollama com.jeju.ollama-gate; do launchctl bootout $U/$n 2>/dev/null || true; rm -f $LA/$n.plist; done
  echo "내림(토큰 파일 $J/ollama_token은 남김)"
  ;;
esac
