"""WebSocket 联调验证：连 WS → 触发讨论 → 监听全部事件直到结束。"""
import asyncio
import json
import sys
import urllib.request

sys.path.insert(0, ".")

import websockets

BASE = "http://127.0.0.1:8000"
WS_URL = "ws://127.0.0.1:8000/ws"


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


async def main() -> None:
    async with websockets.connect(WS_URL) as ws:
        init = json.loads(await ws.recv())
        print(f"[init] 历史消息 {len(init['messages'])} 条, running={init['running']}")

        res = post("/api/discuss", {
            "question": "用一句话回答：静态类型语言最大的好处是什么？",
            "max_rounds": 1,
        })
        print(f"[discuss] {res}")
        if not res.get("ok"):
            sys.exit(1)

        summary_count = 0
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=600)
            ev = json.loads(raw)
            t = ev["type"]
            if t == "message":
                m = ev["message"]
                print(f"[msg] {m['member_name']} round={m['round']} "
                      f"action={m['action']} target={m.get('target_id')} "
                      f"status={m['status']} content={m['content'][:60]!r}")
                if m["action"] == "summary":
                    summary_count += 1
            elif t == "typing":
                print(f"[typing] {ev['member_name']} (round {ev['round']})")
            elif t == "round_start":
                print(f"[round_start] {ev['round']}/{ev['max_rounds']}")
            elif t == "finished":
                print(f"[finished] stopped={ev.get('stopped')}")
                break
            elif t == "error":
                print(f"[error] {ev.get('error')}")
                break
            else:
                print(f"[{t}] {ev}")

        if summary_count == 0:
            print("!! 缺少总结消息")
            sys.exit(1)
        print("WS 联调通过")


if __name__ == "__main__":
    asyncio.run(main())
