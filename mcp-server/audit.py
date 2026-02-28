# audit.py
import json
import uuid
from datetime import datetime

import os

class AuditLogger:
    def __init__(self, log_file=None):
        if log_file is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            log_file = os.path.join(base_dir, "audit_log.json")
        self.log_file = log_file
        self.session_id = str(uuid.uuid4())  # ← missing
        self.step = 0                         # ← missing
        self.session_actions = []             # ← missing

        # write session start entry
        self._write({                         # ← missing
            "type": "session_start",
            "session_id": self.session_id,
            "timestamp": datetime.now().isoformat()
        })
    
    def log(self, tool_name, arguments, result, reasoning=None, decision=None):
        self.step += 1
        entry = {
            "type": "action",
            "session_id": self.session_id,
            "step": self.step,
            "timestamp": datetime.now().isoformat(),
            "tool": tool_name,
            "arguments": arguments,
            "result_preview": result[:500] if result else None,
            "reasoning": reasoning,
            "decision": decision
        }
        self.session_actions.append(entry)
        self._write(entry)
        return entry
    
    def log_review(self, pr_info, diff_sent, review_returned, reasoning=None):
        self.step += 1
        entry = {
            "type": "code_review",
            "session_id": self.session_id,
            "step": self.step,
            "timestamp": datetime.now().isoformat(),
            "pr": pr_info,
            "context_sent": {
                "diff_length": len(diff_sent),
                "diff_preview": diff_sent[:300]
            },
            "review": review_returned,
            "reasoning": reasoning,
            "requires_action": self._extract_critical_issues(review_returned)
        }
        self.session_actions.append(entry)
        self._write(entry)
        return entry
    
    def _extract_critical_issues(self, review_text):
        # pull out anything marked CRITICAL so you can see it at a glance
        lines = review_text.split("\n")
        critical = [line for line in lines if "[CRITICAL]" in line]
        return critical if critical else []
    
    def end_session(self, approved=None, notes=None):
        entry = {
            "type": "session_end",
            "session_id": self.session_id,
            "timestamp": datetime.now().isoformat(),
            "total_steps": self.step,
            "approved": approved,
            "notes": notes,
            "action_summary": [
                {"step": a["step"], "tool": a["tool"]} 
                for a in self.session_actions
            ]
        }
        self._write(entry)
    
    def _write(self, entry):
        with open(self.log_file, "a") as f:
            f.write(json.dumps(entry) + "\n")