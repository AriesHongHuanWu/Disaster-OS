import os
import json
import base64
import io
import re
from fastapi import FastAPI, File, UploadFile, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from PIL import Image, ImageDraw, ImageFont
import google.generativeai as genai

app = FastAPI(title="Disaster Insight OS")

# 設定 Google Gemini API Key (優先讀取環境變數，以利上線部署)
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "AIzaSyCMEL8poBH48Z7UrSSGQNxbRgB93m4jE_k")
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-3-flash-preview')

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "message": "Disaster Insight OS is running smoothly."}

@app.get("/", response_class=HTMLResponse)
async def read_root():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            content = f.read()
            return HTMLResponse(content=content, headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"})
    except FileNotFoundError:
        return HTMLResponse(content="找不到 index.html 檔案，請確認檔案位置。", status_code=404)

@app.post("/api/segment")
async def segment_image(request: Request):
    try:
        form = await request.form()
        file = form.get("file")
        file_before = form.get("file_before")
        location = form.get("location", "未指定座標")
        coordinates = form.get("coordinates", "")
        
        image = None
        image_before = None
        
        if file and hasattr(file, 'read'):
            contents = await file.read()
            image = Image.open(io.BytesIO(contents)).convert("RGB")
            
        if file_before and hasattr(file_before, 'read'):
            contents_before = await file_before.read()
            image_before = Image.open(io.BytesIO(contents_before)).convert("RGB")
            
        if not image and not image_before:
            return JSONResponse(status_code=400, content={"success": False, "message": "至少需要提供一張圖片"})
            
        if not image and image_before:
            image = image_before
            image_before = None

        prompt_inputs = []
        if image_before:
            prompt_inputs.append("這是一張【災前】的歷史影像，作為比對基準：")
            prompt_inputs.append(image_before)
            
        prompt_inputs.append("這是【目前災後 (最新)】的影像：")
        prompt_inputs.append(image)
        
        prompt = f"""
        You are an advanced AI for Disaster Management. Location context: {location} (Coords: {coordinates}).
        If a 'before' image is provided, aggressively compare it with the 'current' image to identify destroyed buildings, flooded areas, or landslides.
        Utilize your built-in knowledge and visual evidence to infer the real-world disaster situation for this location.
        Return EXACTLY a raw valid JSON (no markdown wrapping) in TRADITIONAL CHINESE (繁體中文).
        
        JSON STRUCTURE:
        {{
          "disaster_probabilities": [{{"cause": "string", "percentage": number}}],
          "live_disaster_verification": {{"status": "已確認 / 未核實 / 無嚴重災情", "news_summary": "利用影像證據與內部知識，確認該地點最新是否發生災難，並簡述事實"}},
          "estimated_cost": "string",
          "bounding_boxes": [
            {{
              "label": "string",
              "severity": "string",
              "color": "blue or red",
              "shape_type": "area or line",
              "box": [ymin, xmin, ymax, xmax] 
            }}
          ],
          "infrastructure_analysis": [
            {{"title": "string", "description": "string", "icon": "domain_disabled"}}
          ],
          "rescue_innovations": [
             {{"type": "自動化無人機投遞點 / 避難區 / 醫療站", "description": "string", "icon": "flight_takeoff"}}
          ],
          "recovery_plan": [
            {{"step": "string", "title": "string", "description": "string"}}
          ],
          "resource_estimating": [
            {{"item": "string", "quantity": "string", "urgency": "高/中/低"}}
          ],
          "secondary_disasters": [
            {{"warning": "string", "probability": number}}
          ]
        }}
        """
        prompt_inputs.append(prompt)
        
        response = model.generate_content(prompt_inputs)
        response_text = response.text.strip()
        response_text = re.sub(r'^```(json)?\n?', '', response_text)
        response_text = re.sub(r'\n?```$', '', response_text).strip()
        
        try:
            result_data = json.loads(response_text)
        except json.JSONDecodeError:
            result_data = {
                "disaster_probabilities": [{"cause": "解析異常", "percentage": 100}],
                "estimated_cost": "無法預估",
                "bounding_boxes": [],
                "infrastructure_analysis": [],
                "rescue_innovations": [],
                "recovery_plan": [],
                "resource_estimating": [],
                "secondary_disasters": []
            }

        width, height = image.size
        # 用於半透明填充
        overlay = Image.new('RGBA', image.size, (255, 255, 255, 0))
        draw = ImageDraw.Draw(overlay)
        # 用於實線和文字
        orig_draw = ImageDraw.Draw(image)

        color_map = { "blue": (0, 0, 255, 80), "red": (255, 0, 0, 80), "yellow": (255, 255, 0, 80), "orange": (255, 165, 0, 80), "purple": (128, 0, 128, 80) }
        solid_color_map = { "blue": (0, 0, 255, 255), "red": (255, 0, 0, 255), "yellow": (220, 220, 0, 255), "orange": (255, 165, 0, 255), "purple": (128, 0, 128, 255) }
        
        for bbox in result_data.get("bounding_boxes", []):
            try:
                ymin, xmin, ymax, xmax = bbox["box"]
                abs_xmin, abs_ymin = int((xmin / 1000.0) * width), int((ymin / 1000.0) * height)
                abs_xmax, abs_ymax = int((xmax / 1000.0) * width), int((ymax / 1000.0) * height)
                c_name = str(bbox.get("color", "red")).lower()
                shape_type = bbox.get("shape_type", "area").lower()
                
                if shape_type == "line":
                    draw.line([(abs_xmin, abs_ymin), (abs_xmax, abs_ymax)], fill=color_map.get(c_name, (255,0,0,80)), width=12)
                    orig_draw.line([(abs_xmin, abs_ymin), (abs_xmax, abs_ymax)], fill=solid_color_map.get(c_name, (255,0,0,255)), width=4)
                else:
                    draw.rectangle([abs_xmin, abs_ymin, abs_xmax, abs_ymax], fill=color_map.get(c_name, (255,0,0,80)))
                    orig_draw.rectangle([abs_xmin, abs_ymin, abs_xmax, abs_ymax], outline=solid_color_map.get(c_name, (255,0,0,255)), width=3)
            except Exception:
                continue

        result_img = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
        buffered = io.BytesIO()
        result_img.save(buffered, format="JPEG")
        img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
        
        result_data["segmented_image"] = f"data:image/jpeg;base64,{img_str}"
        result_data["success"] = True
        return JSONResponse(content=result_data)
        
    except Exception as e:
        print(f"Error: {e}")
        error_msg = str(e).lower()
        if "429" in error_msg or "quota" in error_msg:
            print("API Quota exceeded, returning mock data for demonstration.")
            mock_data = {
                "success": True,
                "disaster_probabilities": [{"cause": "(系統模擬) 嚴重淹水", "percentage": 95}, {"cause": "土石流", "percentage": 25}],
                "live_disaster_verification": {"status": "模擬展示模式", "news_summary": "注意：由於 API 額度耗盡，此為展示用模擬資料，非真實即時數據。"},
                "estimated_cost": "約 NT$ 15,000,000 (模擬數據)",
                "bounding_boxes": [],
                "infrastructure_analysis": [{"title": "聯外道路中斷", "description": "模擬測試：省道部分路段遭泥流掩蓋。", "icon": "add_road"}],
                "rescue_innovations": [{"type": "無人機物資投遞點", "description": "建議於高地學校操場建立臨時起降場。", "icon": "flight_takeoff"}],
                "recovery_plan": [{"step": "Phase 1", "title": "緊急排水", "description": "調派大型抽水機組前往重災區。"}],
                "resource_estimating": [{"item": "乾淨飲用水", "quantity": "5000箱", "urgency": "高"}],
                "secondary_disasters": [{"warning": "水源污染與傳染病風險", "probability": 70}]
            }
            if image:
                width, height = image.size
                overlay = Image.new('RGBA', image.size, (255, 255, 255, 0))
                draw = ImageDraw.Draw(overlay)
                draw.rectangle([int(width*0.2), int(height*0.2), int(width*0.8), int(height*0.8)], fill=(255,0,0,80), outline=(255,0,0,255), width=5)
                result_img = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
                buffered = io.BytesIO()
                result_img.save(buffered, format="JPEG")
                img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
                mock_data["segmented_image"] = f"data:image/jpeg;base64,{img_str}"
            
            return JSONResponse(content=mock_data)
        
        # 對於其他錯誤，回傳 200 OK 搭配 success: False，避免前端噴 500 Error
        return JSONResponse(status_code=200, content={"success": False, "message": str(e)})

if __name__ == "__main__":
    import uvicorn
    # 改為 8005 Port
    uvicorn.run(app, host="0.0.0.0", port=8005)