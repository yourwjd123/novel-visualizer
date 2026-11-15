"""Only launched by desktop_e2e.py; accepts dialogs on behalf of that test."""

import sys
import json
import os
from PySide6.QtWidgets import QApplication
from novelviz.desktop import Desktop, LocalPage
from novelviz.demo import seed_visual_demo
from novelviz.storage import Store

# Regression fixture: large valid model output, without using a paid service.
if os.environ.get("NOVELVIZ_E2E_LONG_RESPONSE") == "1":
    import novelviz.desktop as desktop

    original_text_call = desktop.text_call

    def long_response(params, *args, **kwargs):
        answer = original_text_call(params, *args, **kwargs)
        if params.get("template", {}).get("id") == "consult":
            return answer + "演示长回复，用于测试浮窗交互。" * 3000
        if (
            params.get("provider") == "demo"
            and params.get("template", {}).get("format") == "assets"
        ):
            data = json.loads(answer)
            data["note"] = "演示长回复，用于测试浮窗交互。" * 3000
            return json.dumps(data, ensure_ascii=False)
        return answer

    desktop.text_call = long_response

LocalPage.javaScriptConfirm = lambda self, origin, message: True
app = QApplication([])
app.setApplicationName("NovelVisualizerE2E")
app.setOrganizationName("NovelStudioTests")
store = Store(sys.argv[1])
seed_visual_demo(store)
window = Desktop(sys.argv[1])
window.resize(1440, 1000)
window.show()
sys.exit(app.exec())
