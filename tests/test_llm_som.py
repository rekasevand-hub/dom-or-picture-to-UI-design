from src.app.services.llm.llm_service import build_som_prompt

def test_build_som_prompt_shape():
    som = {"image": "a.png", "size": [100, 80], "containers": [], "elements": [],
           "provenance": {"route": "dom"}}
    msgs = build_som_prompt(som, "BASE64==")
    assert msgs[0]["role"] == "system"
    parts = msgs[1]["content"]
    assert any(p["type"] == "image_url" and "BASE64==" in p["image_url"]["url"] for p in parts)
    assert any("DesignSpec" in p["text"] for p in parts if p["type"] == "text")
