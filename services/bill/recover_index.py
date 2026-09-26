import json

transcript_path = "/home/pupoin/.gemini/antigravity-cli/brain/9d7dc91c-4fcf-49cb-8245-92fa7104c698/.system_generated/logs/transcript_full.jsonl"
file_path = "/home/pupoin/pupoinWeb/bill/front/static/index.html"

with open(file_path, "r") as f:
    content = f.read()

with open(transcript_path, "r") as f:
    for line in f:
        try:
            entry = json.loads(line)
        except:
            continue
            
        if entry.get("type") == "PLANNER_RESPONSE" and "tool_calls" in entry:
            for call in entry["tool_calls"]:
                if call["name"] in ["replace_file_content", "multi_replace_file_content"]:
                    args = call.get("args", {})
                    if args.get("TargetFile", "").endswith("index.html"):
                        # If this is the bad commit that broke things, STOP
                        if "Implement sticky column, horizontal scroll, and remove action column" in args.get("Description", ""):
                            break
                        
                        if call["name"] == "replace_file_content":
                            target = args.get("TargetContent", "")
                            repl = args.get("ReplacementContent", "")
                            if target and target in content:
                                content = content.replace(target, repl)
                        elif call["name"] == "multi_replace_file_content":
                            chunks = args.get("ReplacementChunks", [])
                            for chunk in chunks:
                                target = chunk.get("TargetContent", "")
                                repl = chunk.get("ReplacementContent", "")
                                if target and target in content:
                                    content = content.replace(target, repl)

with open(file_path, "w") as f:
    f.write(content)

print("Recovered index.html")
