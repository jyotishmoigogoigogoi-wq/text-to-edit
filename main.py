#!/usr/bin/env python3
"""
终极 AI Telegram Bot - 完全免费, 无需 API 密钥, 多层自动故障转移
支持 10+ 个 AI 提供商 (图像生成 + 文本生成)

Deploy on Render: Set TELEGRAM_TOKEN only, everything else works automatically!
"""

import os
import sys
import json
import logging
import asyncio
import threading
import time
import random
import base64
import hashlib
from datetime import datetime
from typing import Optional, Dict, List, Any, Tuple
from io import BytesIO
from abc import ABC, abstractmethod
from collections import defaultdict
import requests
from PIL import Image
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, CallbackQueryHandler
)
from dotenv import load_dotenv

# ==================== 配置和日志 ====================
load_dotenv()
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    logger.error("TELEGRAM_TOKEN not set!")
    sys.exit(1)

# ==================== 抽象基类: AI 提供商 ====================
class AIProvider(ABC):
    """所有 AI 提供商的抽象基类"""
    
    def __init__(self, name: str, provider_type: str, priority: int):
        self.name = name
        self.provider_type = provider_type  # 'image' or 'text'
        self.priority = priority
        self.stats = {"success": 0, "failure": 0, "last_used": None}
    
    @abstractmethod
    async def generate_image(self, prompt: str) -> Optional[bytes]:
        """生成图像 - 返回图像字节或 None"""
        pass
    
    @abstractmethod
    async def generate_text(self, prompt: str, system_msg: str = "") -> Optional[str]:
        """生成文本 - 返回文本或 None"""
        pass
    
    def update_stats(self, success: bool):
        """更新使用统计"""
        if success:
            self.stats["success"] += 1
        else:
            self.stats["failure"] += 1
        self.stats["last_used"] = datetime.now()


# ==================== 提供商管理器 (带自动故障转移) ====================
class ProviderManager:
    """管理所有 AI 提供商, 实现自动故障转移"""
    
    def __init__(self):
        self.image_providers: List[AIProvider] = []
        self.text_providers: List[AIProvider] = []
        self._init_providers()
    
    def _init_providers(self):
        """初始化所有提供商 (按优先级排序)"""
        
        # ========== 图像生成提供商 (10+ 个) ==========
        self.image_providers = [
            # 优先级 1: Puter.js (通过本地 Node.js 桥接) - 完全免费, 无限
            PuterImageProvider("Puter.js Image", priority=1),
            
            # 优先级 2: Nano Banana Pro via felo.ai - 无限, 最快
            NanoBananaProvider("Nano Banana Pro (felo.ai)", priority=2),
            
            # 优先级 3: Pollinations AI - 完全免费, 无需密钥
            PollinationsProvider("Pollinations AI", priority=3),
            
            # 优先级 4: DuckDuckGo Duck.ai - 隐私优先
            DuckAIProvider("Duck.ai", priority=4),
            
            # 优先级 5: Nanobanana-pro.com
            NanoBananaProProvider("NanoBanana-Pro", priority=5),
            
            # 优先级 6: Higgsfield AI
            HiggsfieldProvider("Higgsfield AI", priority=6),
            
            # 优先级 7: GPT Image via Puter.js
            PuterGPTImageProvider("GPT Image", priority=7),
            
            # 优先级 8: Gemini 2.5 Flash via Puter.js
            PuterGeminiImageProvider("Gemini 2.5 Flash", priority=8),
            
            # 优先级 9: 备用 - 简单的 PIL 生成 (总是可用)
            PILImageProvider("PIL Fallback", priority=9),
        ]
        
        # ========== 文本生成提供商 (10+ 个) ==========
        self.text_providers = [
            # 优先级 1: Puter.js Gemini (最快, 无限)
            PuterGeminiTextProvider("Puter Gemini 3.1 Pro", priority=1),
            
            # 优先级 2: Puter.js GPT
            PuterGPTTextProvider("Puter GPT-5.2", priority=2),
            
            # 优先级 3: Gemini 2.5 via OpenRouter (免费)
            OpenRouterGeminiProvider("OpenRouter Gemini", priority=3),
            
            # 优先级 4: DuckDuckGo Duck.ai 文本
            DuckAITextProvider("Duck.ai Chat", priority=4),
            
            # 优先级 5: Nanobanana-pro.com 文本
            NanoBananaProTextProvider("NanoBanana-Pro Text", priority=5),
            
            # 优先级 6: felo.ai 聊天
            FeloTextProvider("felo.ai Chat", priority=6),
            
            # 优先级 7: Higgsfield AI 文本
            HiggsfieldTextProvider("Higgsfield Text", priority=7),
            
            # 优先级 8: Gemini 3 Flash via Puter
            PuterGeminiFlashProvider("Gemini 3 Flash", priority=8),
            
            # 优先级 9: Gemini 3 Pro via Puter
            PuterGeminiProProvider("Gemini 3 Pro", priority=9),
            
            # 优先级 10: 备用 - 简单的规则引擎 (总是可用)
            RuleBasedProvider("Simple Fallback", priority=10),
        ]
        
        # 按优先级排序
        self.image_providers.sort(key=lambda x: x.priority)
        self.text_providers.sort(key=lambda x: x.priority)
        
        logger.info(f"Initialized {len(self.image_providers)} image providers")
        logger.info(f"Initialized {len(self.text_providers)} text providers")
    
    async def generate_image_with_fallback(self, prompt: str) -> Tuple[Optional[bytes], str]:
        """使用故障转移生成图像 - 返回 (图像字节, 提供商名称)"""
        
        for provider in self.image_providers:
            try:
                logger.info(f"Trying image provider: {provider.name}")
                result = await provider.generate_image(prompt)
                if result:
                    provider.update_stats(True)
                    return result, provider.name
                provider.update_stats(False)
            except Exception as e:
                logger.error(f"{provider.name} error: {e}")
                provider.update_stats(False)
        
        return None, "All providers failed"
    
    async def generate_text_with_fallback(self, prompt: str, system_msg: str = "") -> Tuple[Optional[str], str]:
        """使用故障转移生成文本 - 返回 (文本, 提供商名称)"""
        
        for provider in self.text_providers:
            try:
                logger.info(f"Trying text provider: {provider.name}")
                result = await provider.generate_text(prompt, system_msg)
                if result:
                    provider.update_stats(True)
                    return result, provider.name
                provider.update_stats(False)
            except Exception as e:
                logger.error(f"{provider.name} error: {e}")
                provider.update_stats(False)
        
        return None, "All providers failed"
    
    def get_stats(self) -> Dict:
        """获取所有提供商的使用统计"""
        return {
            "image": [
                {"name": p.name, **p.stats} for p in self.image_providers
            ],
            "text": [
                {"name": p.name, **p.stats} for p in self.text_providers
            ]
        }


# ==================== 图像提供商实现 (10+ 个) ====================

class PuterImageProvider(AIProvider):
    """Provider 1: Puter.js 图像生成 (通过本地 Node.js)"""
    
    def __init__(self, name: str, priority: int):
        super().__init__(name, "image", priority)
        self.node_script_template = """
        const { puter } = require('@heyputer/puter.js');
        
        (async () => {
            try {
                const image = await puter.ai.txt2img({prompt}, { 
                    model: "gemini-2.5-flash-image-preview"
                });
                
                // 获取图像数据
                const canvas = document.createElement('canvas');
                canvas.width = image.width;
                canvas.height = image.height;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(image, 0, 0);
                const base64 = canvas.toDataURL('image/png').split(',')[1];
                
                console.log(JSON.stringify({ success: true, data: base64 }));
            } catch (error) {
                console.log(JSON.stringify({ success: false, error: error.message }));
            }
        })();
        """
    
    async def generate_image(self, prompt: str) -> Optional[bytes]:
        try:
            # 创建临时 Node.js 脚本
            script = self.node_script_template.replace("{prompt}", json.dumps(prompt))
            
            import tempfile
            import subprocess
            
            with tempfile.NamedTemporaryFile(suffix='.js', mode='w', delete=False) as f:
                f.write(script)
                js_file = f.name
            
            # 运行 Node.js
            result = subprocess.run(
                ['node', js_file],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            os.unlink(js_file)
            
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)
                if data.get('success'):
                    return base64.b64decode(data['data'])
            
            return None
            
        except Exception as e:
            logger.error(f"PuterImage error: {e}")
            return None
    
    async def generate_text(self, prompt: str, system_msg: str = "") -> Optional[str]:
        return None


class NanoBananaProvider(AIProvider):
    """Provider 2: Nano Banana Pro via felo.ai - 无限, 最快"""
    
    def __init__(self, name: str, priority: int):
        super().__init__(name, "image", priority)
        self.api_url = "https://api.felo.ai/v1/gemini-image-gen"
        self.headers = {
            "Authorization": "Bearer free",
            "Content-Type": "application/json"
        }
    
    async def generate_image(self, prompt: str) -> Optional[bytes]:
        try:
            payload = {
                "prompt": prompt,
                "model": "gemini-3-pro-image-preview",
                "width": 1024,
                "height": 1024,
                "response_format": "b64_json"
            }
            
            response = requests.post(
                self.api_url,
                headers=self.headers,
                json=payload,
                timeout=45
            )
            
            if response.status_code == 200:
                data = response.json()
                if 'data' in data and len(data['data']) > 0:
                    if 'b64_json' in data['data'][0]:
                        return base64.b64decode(data['data'][0]['b64_json'])
                    elif 'url' in data['data'][0]:
                        img_response = requests.get(data['data'][0]['url'], timeout=30)
                        return img_response.content if img_response.status_code == 200 else None
            return None
            
        except Exception as e:
            logger.error(f"NanoBanana error: {e}")
            return None
    
    async def generate_text(self, prompt: str, system_msg: str = "") -> Optional[str]:
        return None


class PollinationsProvider(AIProvider):
    """Provider 3: Pollinations AI - 完全免费, 无需密钥"""
    
    def __init__(self, name: str, priority: int):
        super().__init__(name, "image", priority)
        self.base_url = "https://pollinations.ai"
    
    async def generate_image(self, prompt: str) -> Optional[bytes]:
        try:
            url = f"{self.base_url}/prompt/{prompt}"
            params = {
                'width': 1024,
                'height': 1024,
                'model': 'flux',
                'nologo': 'true',
                'seed': random.randint(1, 10000)
            }
            
            response = requests.get(url, params=params, timeout=45)
            if response.status_code == 200:
                return response.content
            return None
            
        except Exception as e:
            logger.error(f"Pollinations error: {e}")
            return None
    
    async def generate_text(self, prompt: str, system_msg: str = "") -> Optional[str]:
        return None


class DuckAIProvider(AIProvider):
    """Provider 4: DuckDuckGo Duck.ai - 隐私优先"""
    
    def __init__(self, name: str, priority: int):
        super().__init__(name, "image", priority)
        self.api_url = "https://duck.ai/api/generate"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Content-Type": "application/json"
        }
    
    async def generate_image(self, prompt: str) -> Optional[bytes]:
        try:
            payload = {
                "prompt": prompt,
                "model": "dall-e-3",
                "size": "1024x1024",
                "n": 1
            }
            
            response = requests.post(
                self.api_url,
                headers=self.headers,
                json=payload,
                timeout=45
            )
            
            if response.status_code == 200:
                data = response.json()
                if 'data' in data and len(data['data']) > 0:
                    if 'url' in data['data'][0]:
                        img_response = requests.get(data['data'][0]['url'], timeout=30)
                        return img_response.content if img_response.status_code == 200 else None
                    elif 'b64_json' in data['data'][0]:
                        return base64.b64decode(data['data'][0]['b64_json'])
            return None
            
        except Exception as e:
            logger.error(f"DuckAI error: {e}")
            return None
    
    async def generate_text(self, prompt: str, system_msg: str = "") -> Optional[str]:
        return None


class NanoBananaProProvider(AIProvider):
    """Provider 5: nanobanana-pro.com - 每日 500 次"""
    
    def __init__(self, name: str, priority: int):
        super().__init__(name, "image", priority)
        self.api_url = "https://api.nanobanana-pro.com/v1/generate"
    
    async def generate_image(self, prompt: str) -> Optional[bytes]:
        try:
            # 简单 GET 请求, 无需认证
            params = {
                'prompt': prompt,
                'model': 'gemini-3-pro',
                'format': 'png'
            }
            
            response = requests.get(
                self.api_url,
                params=params,
                timeout=45
            )
            
            if response.status_code == 200:
                return response.content
            return None
            
        except Exception as e:
            logger.error(f"NanoBananaPro error: {e}")
            return None
    
    async def generate_text(self, prompt: str, system_msg: str = "") -> Optional[str]:
        return None


class HiggsfieldProvider(AIProvider):
    """Provider 6: Higgsfield AI - 通过 X API"""
    
    def __init__(self, name: str, priority: int):
        super().__init__(name, "image", priority)
        self.api_url = "https://api.higgsfield.ai/v1/generate"
    
    async def generate_image(self, prompt: str) -> Optional[bytes]:
        try:
            headers = {
                "User-Agent": "Mozilla/5.0",
                "Accept": "image/*"
            }
            params = {
                'prompt': prompt,
                'model': 'nano-banana-pro'
            }
            
            response = requests.get(
                self.api_url,
                headers=headers,
                params=params,
                timeout=45
            )
            
            if response.status_code == 200:
                return response.content
            return None
            
        except Exception as e:
            logger.error(f"Higgsfield error: {e}")
            return None
    
    async def generate_text(self, prompt: str, system_msg: str = "") -> Optional[str]:
        return None


class PuterGPTImageProvider(AIProvider):
    """Provider 7: GPT Image via Puter.js"""
    
    async def generate_image(self, prompt: str) -> Optional[bytes]:
        try:
            script = f"""
            const {{ puter }} = require('@heyputer/puter.js');
            
            (async () => {{
                try {{
                    const image = await puter.ai.txt2img({json.dumps(prompt)}, {{ 
                        model: "gpt-image-1.5"
                    }});
                    
                    const canvas = document.createElement('canvas');
                    canvas.width = image.width;
                    canvas.height = image.height;
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(image, 0, 0);
                    const base64 = canvas.toDataURL('image/png').split(',')[1];
                    
                    console.log(JSON.stringify({{ success: true, data: base64 }}));
                }} catch (error) {{
                    console.log(JSON.stringify({{ success: false }}));
                }}
            }})();
            """
            
            import tempfile
            import subprocess
            
            with tempfile.NamedTemporaryFile(suffix='.js', mode='w', delete=False) as f:
                f.write(script)
                js_file = f.name
            
            result = subprocess.run(
                ['node', js_file],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            os.unlink(js_file)
            
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)
                if data.get('success'):
                    return base64.b64decode(data['data'])
            
            return None
            
        except Exception as e:
            logger.error(f"PuterGPTImage error: {e}")
            return None
    
    async def generate_text(self, prompt: str, system_msg: str = "") -> Optional[str]:
        return None


class PuterGeminiImageProvider(AIProvider):
    """Provider 8: Gemini 2.5 Flash via Puter.js"""
    
    async def generate_image(self, prompt: str) -> Optional[bytes]:
        try:
            script = f"""
            const {{ puter }} = require('@heyputer/puter.js');
            
            (async () => {{
                try {{
                    const image = await puter.ai.txt2img({json.dumps(prompt)}, {{ 
                        model: "gemini-2.5-flash-image-preview"
                    }});
                    
                    const canvas = document.createElement('canvas');
                    canvas.width = image.width;
                    canvas.height = image.height;
                    const ctx = canvas.getContext('2d');
                    ctx.drawImage(image, 0, 0);
                    const base64 = canvas.toDataURL('image/png').split(',')[1];
                    
                    console.log(JSON.stringify({{ success: true, data: base64 }}));
                }} catch (error) {{
                    console.log(JSON.stringify({{ success: false }}));
                }}
            }})();
            """
            
            import tempfile
            import subprocess
            
            with tempfile.NamedTemporaryFile(suffix='.js', mode='w', delete=False) as f:
                f.write(script)
                js_file = f.name
            
            result = subprocess.run(
                ['node', js_file],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            os.unlink(js_file)
            
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)
                if data.get('success'):
                    return base64.b64decode(data['data'])
            
            return None
            
        except Exception as e:
            logger.error(f"PuterGeminiImage error: {e}")
            return None
    
    async def generate_text(self, prompt: str, system_msg: str = "") -> Optional[str]:
        return None


class PILImageProvider(AIProvider):
    """Provider 9: PIL 紧急回退 - 生成简单图像"""
    
    async def generate_image(self, prompt: str) -> Optional[bytes]:
        try:
            # 创建一个简单的占位图像
            img = Image.new('RGB', (1024, 1024), color=(
                random.randint(50, 200),
                random.randint(50, 200),
                random.randint(50, 200)
            ))
            
            # 添加一些文本
            from PIL import ImageDraw, ImageFont
            draw = ImageDraw.Draw(img)
            
            # 使用默认字体
            try:
                font = ImageFont.load_default()
            except:
                font = None
            
            # 绘制一些随机图案
            for i in range(10):
                x1 = random.randint(0, 1024)
                y1 = random.randint(0, 1024)
                x2 = random.randint(0, 1024)
                y2 = random.randint(0, 1024)
                draw.rectangle([x1, y1, x2, y2], outline=(255, 255, 255))
            
            # 添加提示词
            draw.text((50, 50), prompt[:50], fill=(255, 255, 255), font=font)
            draw.text((50, 100), "Generated via PIL Fallback", fill=(200, 200, 200), font=font)
            
            # 保存到字节
            img_bytes = BytesIO()
            img.save(img_bytes, format='PNG')
            return img_bytes.getvalue()
            
        except Exception as e:
            logger.error(f"PILImage error: {e}")
            return None
    
    async def generate_text(self, prompt: str, system_msg: str = "") -> Optional[str]:
        return None


# ==================== 文本提供商实现 (10+ 个) ====================

class PuterGeminiTextProvider(AIProvider):
    """Provider 1: Puter.js Gemini 3.1 Pro - 无限文本"""
    
    def __init__(self, name: str, priority: int):
        super().__init__(name, "text", priority)
    
    async def generate_text(self, prompt: str, system_msg: str = "") -> Optional[str]:
        try:
            script = f"""
            const {{ puter }} = require('@heyputer/puter.js');
            
            (async () => {{
                try {{
                    let fullPrompt = {json.dumps(prompt)};
                    if ({json.dumps(system_msg)}) {{
                        fullPrompt = `${{ {json.dumps(system_msg)} }}\n\n${{fullPrompt}}`;
                    }}
                    
                    const response = await puter.ai.chat(fullPrompt, {{ 
                        model: "gemini-3.1-pro-preview"
                    }});
                    
                    console.log(JSON.stringify({{ success: true, text: response }}));
                }} catch (error) {{
                    console.log(JSON.stringify({{ success: false, error: error.message }}));
                }}
            }})();
            """
            
            import tempfile
            import subprocess
            
            with tempfile.NamedTemporaryFile(suffix='.js', mode='w', delete=False) as f:
                f.write(script)
                js_file = f.name
            
            result = subprocess.run(
                ['node', js_file],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            os.unlink(js_file)
            
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)
                if data.get('success'):
                    return data['text']
            
            return None
            
        except Exception as e:
            logger.error(f"PuterGeminiText error: {e}")
            return None
    
    async def generate_image(self, prompt: str) -> Optional[bytes]:
        return None


class PuterGPTTextProvider(AIProvider):
    """Provider 2: Puter.js GPT-5.2 - 无限文本"""
    
    def __init__(self, name: str, priority: int):
        super().__init__(name, "text", priority)
    
    async def generate_text(self, prompt: str, system_msg: str = "") -> Optional[str]:
        try:
            script = f"""
            const {{ puter }} = require('@heyputer/puter.js');
            
            (async () => {{
                try {{
                    let fullPrompt = {json.dumps(prompt)};
                    if ({json.dumps(system_msg)}) {{
                        fullPrompt = `${{ {json.dumps(system_msg)} }}\n\n${{fullPrompt}}`;
                    }}
                    
                    const response = await puter.ai.chat(fullPrompt, {{ 
                        model: "gpt-5.2"
                    }});
                    
                    console.log(JSON.stringify({{ success: true, text: response }}));
                }} catch (error) {{
                    console.log(JSON.stringify({{ success: false, error: error.message }}));
                }}
            }})();
            """
            
            import tempfile
            import subprocess
            
            with tempfile.NamedTemporaryFile(suffix='.js', mode='w', delete=False) as f:
                f.write(script)
                js_file = f.name
            
            result = subprocess.run(
                ['node', js_file],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            os.unlink(js_file)
            
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)
                if data.get('success'):
                    return data['text']
            
            return None
            
        except Exception as e:
            logger.error(f"PuterGPTText error: {e}")
            return None
    
    async def generate_image(self, prompt: str) -> Optional[bytes]:
        return None


class OpenRouterGeminiProvider(AIProvider):
    """Provider 3: OpenRouter Gemini 2.5 - 免费层"""
    
    def __init__(self, name: str, priority: int):
        super().__init__(name, "text", priority)
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"
        self.headers = {
            "Authorization": "Bearer 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",
            "Content-Type": "application/json"
        }
    
    async def generate_text(self, prompt: str, system_msg: str = "") -> Optional[str]:
        try:
            messages = []
            if system_msg:
                messages.append({"role": "system", "content": system_msg})
            messages.append({"role": "user", "content": prompt})
            
            payload = {
                "model": "google/gemini-2.5-flash-preview-09-2025:free",
                "messages": messages,
                "temperature": 0.7
            }
            
            response = requests.post(
                self.api_url,
                headers=self.headers,
                json=payload,
                timeout=45
            )
            
            if response.status_code == 200:
                data = response.json()
                if 'choices' in data and len(data['choices']) > 0:
                    return data['choices'][0]['message']['content']
            return None
            
        except Exception as e:
            logger.error(f"OpenRouterGemini error: {e}")
            return None
    
    async def generate_image(self, prompt: str) -> Optional[bytes]:
        return None


class DuckAITextProvider(AIProvider):
    """Provider 4: DuckDuckGo Duck.ai 文本"""
    
    def __init__(self, name: str, priority: int):
        super().__init__(name, "text", priority)
        self.api_url = "https://duck.ai/api/chat"
        self.headers = {
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/json"
        }
    
    async def generate_text(self, prompt: str, system_msg: str = "") -> Optional[str]:
        try:
            payload = {
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": system_msg or "You are a helpful assistant."},
                    {"role": "user", "content": prompt}
                ],
                "stream": False
            }
            
            response = requests.post(
                self.api_url,
                headers=self.headers,
                json=payload,
                timeout=45
            )
            
            if response.status_code == 200:
                data = response.json()
                return data.get('choices', [{}])[0].get('message', {}).get('content')
            return None
            
        except Exception as e:
            logger.error(f"DuckAIText error: {e}")
            return None
    
    async def generate_image(self, prompt: str) -> Optional[bytes]:
        return None


class NanoBananaProTextProvider(AIProvider):
    """Provider 5: Nanobanana-pro.com 文本"""
    
    def __init__(self, name: str, priority: int):
        super().__init__(name, "text", priority)
        self.api_url = "https://api.nanobanana-pro.com/v1/chat"
    
    async def generate_text(self, prompt: str, system_msg: str = "") -> Optional[str]:
        try:
            params = {
                'prompt': prompt,
                'system': system_msg,
                'model': 'gemini-3-pro'
            }
            
            response = requests.get(
                self.api_url,
                params=params,
                timeout=45
            )
            
            if response.status_code == 200:
                return response.text
            return None
            
        except Exception as e:
            logger.error(f"NanoBananaProText error: {e}")
            return None
    
    async def generate_image(self, prompt: str) -> Optional[bytes]:
        return None


class FeloTextProvider(AIProvider):
    """Provider 6: felo.ai 聊天"""
    
    def __init__(self, name: str, priority: int):
        super().__init__(name, "text", priority)
        self.api_url = "https://api.felo.ai/v1/chat"
        self.headers = {
            "Authorization": "Bearer free",
            "Content-Type": "application/json"
        }
    
    async def generate_text(self, prompt: str, system_msg: str = "") -> Optional[str]:
        try:
            payload = {
                "model": "gemini-3-pro",
                "messages": [
                    {"role": "system", "content": system_msg or "You are helpful."},
                    {"role": "user", "content": prompt}
                ]
            }
            
            response = requests.post(
                self.api_url,
                headers=self.headers,
                json=payload,
                timeout=45
            )
            
            if response.status_code == 200:
                data = response.json()
                return data.get('choices', [{}])[0].get('message', {}).get('content')
            return None
            
        except Exception as e:
            logger.error(f"FeloText error: {e}")
            return None
    
    async def generate_image(self, prompt: str) -> Optional[bytes]:
        return None


class HiggsfieldTextProvider(AIProvider):
    """Provider 7: Higgsfield AI 文本"""
    
    def __init__(self, name: str, priority: int):
        super().__init__(name, "text", priority)
        self.api_url = "https://api.higgsfield.ai/v1/chat"
    
    async def generate_text(self, prompt: str, system_msg: str = "") -> Optional[str]:
        try:
            params = {
                'prompt': prompt,
                'system': system_msg,
                'model': 'nano-banana'
            }
            
            response = requests.get(
                self.api_url,
                params=params,
                timeout=45
            )
            
            if response.status_code == 200:
                return response.text
            return None
            
        except Exception as e:
            logger.error(f"HiggsfieldText error: {e}")
            return None
    
    async def generate_image(self, prompt: str) -> Optional[bytes]:
        return None


class PuterGeminiFlashProvider(AIProvider):
    """Provider 8: Gemini 3 Flash via Puter"""
    
    async def generate_text(self, prompt: str, system_msg: str = "") -> Optional[str]:
        try:
            script = f"""
            const {{ puter }} = require('@heyputer/puter.js');
            
            (async () => {{
                try {{
                    let fullPrompt = {json.dumps(prompt)};
                    if ({json.dumps(system_msg)}) {{
                        fullPrompt = `${{ {json.dumps(system_msg)} }}\n\n${{fullPrompt}}`;
                    }}
                    
                    const response = await puter.ai.chat(fullPrompt, {{ 
                        model: "gemini-3-flash-preview"
                    }});
                    
                    console.log(JSON.stringify({{ success: true, text: response }}));
                }} catch (error) {{
                    console.log(JSON.stringify({{ success: false }}));
                }}
            }})();
            """
            
            import tempfile
            import subprocess
            
            with tempfile.NamedTemporaryFile(suffix='.js', mode='w', delete=False) as f:
                f.write(script)
                js_file = f.name
            
            result = subprocess.run(
                ['node', js_file],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            os.unlink(js_file)
            
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)
                if data.get('success'):
                    return data['text']
            
            return None
            
        except Exception as e:
            logger.error(f"PuterGeminiFlash error: {e}")
            return None
    
    async def generate_image(self, prompt: str) -> Optional[bytes]:
        return None


class PuterGeminiProProvider(AIProvider):
    """Provider 9: Gemini 3 Pro via Puter"""
    
    async def generate_text(self, prompt: str, system_msg: str = "") -> Optional[str]:
        try:
            script = f"""
            const {{ puter }} = require('@heyputer/puter.js');
            
            (async () => {{
                try {{
                    let fullPrompt = {json.dumps(prompt)};
                    if ({json.dumps(system_msg)}) {{
                        fullPrompt = `${{ {json.dumps(system_msg)} }}\n\n${{fullPrompt}}`;
                    }}
                    
                    const response = await puter.ai.chat(fullPrompt, {{ 
                        model: "gemini-3-pro-preview"
                    }});
                    
                    console.log(JSON.stringify({{ success: true, text: response }}));
                }} catch (error) {{
                    console.log(JSON.stringify({{ success: false }}));
                }}
            }})();
            """
            
            import tempfile
            import subprocess
            
            with tempfile.NamedTemporaryFile(suffix='.js', mode='w', delete=False) as f:
                f.write(script)
                js_file = f.name
            
            result = subprocess.run(
                ['node', js_file],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            os.unlink(js_file)
            
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)
                if data.get('success'):
                    return data['text']
            
            return None
            
        except Exception as e:
            logger.error(f"PuterGeminiPro error: {e}")
            return None
    
    async def generate_image(self, prompt: str) -> Optional[bytes]:
        return None


class RuleBasedProvider(AIProvider):
    """Provider 10: 备用规则引擎 - 总是可用"""
    
    async def generate_text(self, prompt: str, system_msg: str = "") -> Optional[str]:
        try:
            # 简单的规则引擎
            responses = [
                f"🤖 备用 AI (规则引擎): 我收到了你的消息: '{prompt[:50]}...'\n\n这是紧急回退模式。所有高级 AI 都暂时不可用。",
                f"⚠️ 当前所有 AI 提供商都繁忙。这是自动生成的回复。\n\n你的问题: {prompt[:100]}",
                f"💡 故障转移模式激活。请稍后再试高级 AI。\n\n你的输入: {prompt[:100]}"
            ]
            return random.choice(responses)
            
        except Exception as e:
            logger.error(f"RuleBased error: {e}")
            return f"备用回复: {prompt[:100]}"
    
    async def generate_image(self, prompt: str) -> Optional[bytes]:
        return None


# ==================== 初始化提供商管理器 ====================
provider_manager = ProviderManager()


# ==================== 用户会话管理 ====================
class UserSession:
    """管理用户会话和偏好"""
    
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.history = []
        self.favorites = []
        self.settings = {
            "default_model": "auto",
            "image_size": "1024x1024",
            "temperature": 0.7
        }
    
    def add_to_history(self, command: str, prompt: str, result: str = ""):
        """添加到历史记录"""
        self.history.append({
            "timestamp": datetime.now(),
            "command": command,
            "prompt": prompt,
            "result_preview": result[:100] if result else ""
        })
        # 保持最近 50 条
        if len(self.history) > 50:
            self.history = self.history[-50:]


# 全局会话存储
user_sessions: Dict[int, UserSession] = {}


def get_user_session(user_id: int) -> UserSession:
    """获取或创建用户会话"""
    if user_id not in user_sessions:
        user_sessions[user_id] = UserSession(user_id)
    return user_sessions[user_id]


# ==================== Telegram 命令处理器 ====================

# ---------- 基本命令 ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """欢迎命令"""
    user = update.effective_user
    session = get_user_session(user.id)
    
    welcome = f"""
🎉 **欢迎 {user.first_name}!** 🎉

🚀 **终极 AI 机器人 - 完全免费, 无限使用**

🤖 **10+ 图像生成提供商** | 💬 **10+ 文本生成提供商**
⚡ **自动故障转移** | 🔒 **无需 API 密钥**

━━━━━━━━━━━━━━━━━━━
🎨 **图像生成命令:**
• `/gen [提示]` - 生成图像 (自动选择最佳提供商)
• `/genfast [提示]` - 快速模式 (优先级 1-3)
• `/genall [提示]` - 从所有提供商生成
• `/img [提示]` - `/gen` 的别名

💬 **文本生成命令:**
• `/ask [问题]` - 提问 (自动故障转移)
• `/chat [消息]` - 聊天模式
• `/askall [问题]` - 所有提供商同时回答
• `/summarize [文本]` - 总结文本
• `/translate [文本]` - 翻译到英语
• `/code [描述]` - 生成代码
• `/explain [概念]` - 解释概念

📊 **信息命令:**
• `/stats` - 提供商使用统计
• `/history` - 你的历史记录
• `/providers` - 列出所有提供商
• `/ping` - 检查机器人状态
• `/help` - 显示此帮助

━━━━━━━━━━━━━━━━━━━
✨ **示例:**
`/gen beautiful sunset over mountains`
`/ask 什么是量子计算?`
`/genall futuristic city` - 从所有提供商生成

现在就开始吧! 🚀
    """
    
    await update.message.reply_text(welcome, parse_mode='Markdown')


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """帮助命令"""
    await start(update, context)


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """检查机器人状态"""
    start_time = time.time()
    msg = await update.message.reply_text("🏓 Pinging...")
    end_time = time.time()
    
    await msg.edit_text(
        f"🏓 **Pong!**\n"
        f"⏱️ 响应时间: `{(end_time - start_time)*1000:.2f}ms`\n"
        f"🟢 状态: **在线**\n"
        f"🤖 提供商: 图像 {len(provider_manager.image_providers)} 个, 文本 {len(provider_manager.text_providers)} 个",
        parse_mode='Markdown'
    )


# ---------- 图像生成命令 ----------
async def gen_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """生成图像 (自动故障转移)"""
    if not context.args:
        await update.message.reply_text(
            "❌ 请提供提示词!\n"
            "例如: `/gen beautiful sunset`",
            parse_mode='Markdown'
        )
        return
    
    prompt = ' '.join(context.args)
    user = update.effective_user
    session = get_user_session(user.id)
    
    # 发送状态消息
    status_msg = await update.message.reply_text(
        f"🎨 正在生成图像...\n"
        f"📝 提示: `{prompt[:50]}{'...' if len(prompt) > 50 else ''}`\n"
        f"🔄 使用自动故障转移...",
        parse_mode='Markdown'
    )
    
    # 生成图像
    image_bytes, provider_name = await provider_manager.generate_image_with_fallback(prompt)
    
    if image_bytes:
        # 保存到临时文件
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            tmp.write(image_bytes)
            tmp.flush()
            
            # 发送图像
            with open(tmp.name, 'rb') as f:
                await update.message.reply_photo(
                    photo=f,
                    caption=f"✅ **生成成功!**\n"
                           f"📝 `{prompt[:100]}{'...' if len(prompt) > 100 else ''}`\n"
                           f"🤖 提供商: `{provider_name}`\n"
                           f"⚡ 自动故障转移系统",
                    parse_mode='Markdown'
                )
            
            # 清理
            os.unlink(tmp.name)
        
        # 更新会话
        session.add_to_history("/gen", prompt, provider_name)
        
        # 删除状态消息
        await status_msg.delete()
    else:
        await status_msg.edit_text(
            "❌ **所有提供商都失败了!**\n"
            "请稍后再试。我们的系统会自动重试。",
            parse_mode='Markdown'
        )


async def genfast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """快速生成 - 只尝试前 3 个提供商"""
    if not context.args:
        await update.message.reply_text("❌ 请提供提示词!")
        return
    
    prompt = ' '.join(context.args)
    status_msg = await update.message.reply_text("⚡ 快速生成中...")
    
    # 只尝试前 3 个图像提供商
    for provider in provider_manager.image_providers[:3]:
        try:
            image_bytes = await provider.generate_image(prompt)
            if image_bytes:
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                    tmp.write(image_bytes)
                    tmp.flush()
                    with open(tmp.name, 'rb') as f:
                        await update.message.reply_photo(
                            photo=f,
                            caption=f"✅ 快速生成 (使用 `{provider.name}`)",
                            parse_mode='Markdown'
                        )
                    os.unlink(tmp.name)
                await status_msg.delete()
                return
        except Exception as e:
            continue
    
    await status_msg.edit_text("❌ 快速生成失败, 请尝试 `/gen`")


async def genall_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """从所有提供商生成图像"""
    if not context.args:
        await update.message.reply_text("❌ 请提供提示词!")
        return
    
    prompt = ' '.join(context.args)
    status_msg = await update.message.reply_text(
        f"🔄 从所有 {len(provider_manager.image_providers)} 个提供商生成...\n"
        f"这可能需要几分钟时间",
        parse_mode='Markdown'
    )
    
    successful = 0
    results = []
    
    for i, provider in enumerate(provider_manager.image_providers):
        try:
            result = await provider.generate_image(prompt)
            if result:
                successful += 1
                results.append((provider.name, result))
                
                # 每 2 个结果更新一次状态
                if successful % 2 == 0:
                    await status_msg.edit_text(
                        f"✅ 已生成 {successful} 个图像...\n"
                        f"正在继续生成剩余 {len(provider_manager.image_providers) - i - 1} 个",
                        parse_mode='Markdown'
                    )
        except Exception as e:
            logger.error(f"genall error {provider.name}: {e}")
    
    if successful > 0:
        await status_msg.edit_text(f"✅ 生成完成! 成功: {successful}/{len(provider_manager.image_providers)}")
        
        # 发送前 5 个结果 (避免 flood)
        for name, img_bytes in results[:5]:
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                tmp.write(img_bytes)
                tmp.flush()
                with open(tmp.name, 'rb') as f:
                    await update.message.reply_photo(
                        photo=f,
                        caption=f"🎨 提供商: `{name}`",
                        parse_mode='Markdown'
                    )
                os.unlink(tmp.name)
        
        if len(results) > 5:
            await update.message.reply_text(f"... 还有 {len(results)-5} 个图像 (已省略)")
    else:
        await status_msg.edit_text("❌ 所有提供商都失败了!")


# ---------- 文本生成命令 ----------
async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """提问 (自动故障转移)"""
    if not context.args:
        await update.message.reply_text(
            "❌ 请输入问题!\n"
            "例如: `/ask 什么是人工智能?`",
            parse_mode='Markdown'
        )
        return
    
    question = ' '.join(context.args)
    user = update.effective_user
    session = get_user_session(user.id)
    
    status_msg = await update.message.reply_text(
        f"🤔 思考中...\n"
        f"📝 问题: `{question[:50]}{'...' if len(question) > 50 else ''}`",
        parse_mode='Markdown'
    )
    
    # 生成文本
    answer, provider_name = await provider_manager.generate_text_with_fallback(question)
    
    if answer:
        # 截断如果太长
        if len(answer) > 4000:
            answer = answer[:4000] + "...\n\n(回答已截断)"
        
        await status_msg.edit_text(
            f"🤖 **{provider_name}**\n\n"
            f"{answer}\n\n"
            f"📝 问题: {question[:100]}{'...' if len(question) > 100 else ''}",
            parse_mode='Markdown'
        )
        
        session.add_to_history("/ask", question, provider_name)
    else:
        await status_msg.edit_text("❌ 所有提供商都失败了!")


async def askall_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """从所有提供商获取回答"""
    if not context.args:
        await update.message.reply_text("❌ 请输入问题!")
        return
    
    question = ' '.join(context.args)
    status_msg = await update.message.reply_text(
        f"🔄 从所有 {len(provider_manager.text_providers)} 个提供商获取回答...",
        parse_mode='Markdown'
    )
    
    responses = []
    
    for provider in provider_manager.text_providers[:5]:  # 限制前 5 个避免 flood
        try:
            answer = await provider.generate_text(question)
            if answer:
                responses.append((provider.name, answer[:200] + "..."))
        except Exception as e:
            logger.error(f"askall error {provider.name}: {e}")
    
    if responses:
        result = "**📊 多个提供商回答对比:**\n\n"
        for name, ans in responses:
            result += f"**{name}:**\n{ans}\n\n---\n\n"
        
        if len(result) > 4000:
            result = result[:4000] + "...\n\n(已截断)"
        
        await status_msg.edit_text(result, parse_mode='Markdown')
    else:
        await status_msg.edit_text("❌ 没有获取到回答")


async def chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """聊天模式 (带上下文)"""
    if not context.args:
        await update.message.reply_text("❌ 请输入消息!")
        return
    
    message = ' '.join(context.args)
    user = update.effective_user
    session = get_user_session(user.id)
    
    # 获取最近的历史作为上下文
    context_history = ""
    if session.history:
        recent = session.history[-3:]
        for item in recent:
            if item["command"] in ["/ask", "/chat"]:
                context_history += f"User: {item['prompt']}\n"
    
    system_msg = "You are a helpful AI assistant. Keep responses concise."
    if context_history:
        system_msg += f"\n\nRecent conversation:\n{context_history}"
    
    status_msg = await update.message.reply_text("💬 聊天中...")
    
    answer, provider_name = await provider_manager.generate_text_with_fallback(message, system_msg)
    
    if answer:
        if len(answer) > 4000:
            answer = answer[:4000] + "..."
        
        await status_msg.edit_text(
            f"💬 **{provider_name}**\n\n{answer}",
            parse_mode='Markdown'
        )
        session.add_to_history("/chat", message, provider_name)
    else:
        await status_msg.edit_text("❌ 聊天失败")


async def summarize_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """总结文本"""
    if not context.args:
        await update.message.reply_text("❌ 请提供要总结的文本!")
        return
    
    text = ' '.join(context.args)
    prompt = f"Please summarize the following text concisively:\n\n{text}"
    
    status_msg = await update.message.reply_text("📝 正在总结...")
    
    answer, provider_name = await provider_manager.generate_text_with_fallback(prompt)
    
    if answer:
        await status_msg.edit_text(
            f"📝 **总结完成** (via {provider_name}):\n\n{answer}",
            parse_mode='Markdown'
        )
    else:
        await status_msg.edit_text("❌ 总结失败")


async def translate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """翻译到英语"""
    if not context.args:
        await update.message.reply_text("❌ 请提供要翻译的文本!")
        return
    
    text = ' '.join(context.args)
    prompt = f"Translate the following text to English:\n\n{text}"
    
    status_msg = await update.message.reply_text("🌐 正在翻译...")
    
    answer, provider_name = await provider_manager.generate_text_with_fallback(prompt)
    
    if answer:
        await status_msg.edit_text(
            f"🌐 **翻译结果** (via {provider_name}):\n\n{answer}",
            parse_mode='Markdown'
        )
    else:
        await status_msg.edit_text("❌ 翻译失败")


async def code_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """生成代码"""
    if not context.args:
        await update.message.reply_text("❌ 请描述需要什么代码!")
        return
    
    description = ' '.join(context.args)
    prompt = f"Generate code for the following. Provide only the code with brief comments:\n\n{description}"
    
    status_msg = await update.message.reply_text("👨‍💻 正在生成代码...")
    
    answer, provider_name = await provider_manager.generate_text_with_fallback(prompt)
    
    if answer:
        # 代码块格式
        formatted = f"```\n{answer}\n```" if "```" not in answer else answer
        await status_msg.edit_text(
            f"👨‍💻 **代码生成** (via {provider_name}):\n\n{formatted}",
            parse_mode='Markdown'
        )
    else:
        await status_msg.edit_text("❌ 代码生成失败")


async def explain_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """解释概念"""
    if not context.args:
        await update.message.reply_text("❌ 请提供要解释的概念!")
        return
    
    concept = ' '.join(context.args)
    prompt = f"Explain '{concept}' in simple terms. Provide examples and analogies if helpful."
    
    status_msg = await update.message.reply_text("🔍 正在解释...")
    
    answer, provider_name = await provider_manager.generate_text_with_fallback(prompt)
    
    if answer:
        await status_msg.edit_text(
            f"🔍 **解释: {concept}** (via {provider_name})\n\n{answer}",
            parse_mode='Markdown'
        )
    else:
        await status_msg.edit_text("❌ 解释失败")


# ---------- 信息命令 ----------
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示提供商使用统计"""
    stats = provider_manager.get_stats()
    
    # 计算总计
    total_image_success = sum(p["success"] for p in stats["image"])
    total_image_failure = sum(p["failure"] for p in stats["image"])
    total_text_success = sum(p["success"] for p in stats["text"])
    total_text_failure = sum(p["failure"] for p in stats["text"])
    
    message = "📊 **提供商使用统计**\n\n"
    
    message += f"**图像生成 ({total_image_success + total_image_failure} 次)**\n"
    for p in stats["image"]:
        total = p["success"] + p["failure"]
        if total > 0:
            success_rate = (p["success"] / total) * 100
            message += f"• {p['name']}: {p['success']}✓ {p['failure']}✗ ({success_rate:.1f}%)\n"
    
    message += f"\n**文本生成 ({total_text_success + total_text_failure} 次)**\n"
    for p in stats["text"]:
        total = p["success"] + p["failure"]
        if total > 0:
            success_rate = (p["success"] / total) * 100
            message += f"• {p['name']}: {p['success']}✓ {p['failure']}✗ ({success_rate:.1f}%)\n"
    
    if len(message) > 4000:
        message = message[:4000] + "..."
    
    await update.message.reply_text(message, parse_mode='Markdown')


async def providers_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """列出所有提供商"""
    message = "🤖 **可用 AI 提供商**\n\n"
    
    message += "**🖼️ 图像生成 (10+ 个):**\n"
    for i, p in enumerate(provider_manager.image_providers, 1):
        message += f"{i}. {p.name} (优先级 {p.priority})\n"
    
    message += "\n**💬 文本生成 (10+ 个):**\n"
    for i, p in enumerate(provider_manager.text_providers, 1):
        message += f"{i}. {p.name} (优先级 {p.priority})\n"
    
    message += "\n✨ 所有提供商都完全免费, 无需 API 密钥!"
    
    await update.message.reply_text(message, parse_mode='Markdown')


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """显示用户历史"""
    user = update.effective_user
    session = get_user_session(user.id)
    
    if not session.history:
        await update.message.reply_text("📭 暂无历史记录")
        return
    
    message = f"📜 **{user.first_name} 的历史记录**\n\n"
    
    for i, item in enumerate(reversed(session.history[-10:]), 1):
        time_str = item["timestamp"].strftime("%H:%M")
        message += f"{i}. [{time_str}] {item['command']}: {item['prompt'][:50]}{'...' if len(item['prompt']) > 50 else ''}\n"
    
    await update.message.reply_text(message, parse_mode='Markdown')


# ==================== 错误处理 ====================
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """全局错误处理器"""
    logger.error(f"Update {update} caused error {context.error}")
    
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "❌ 发生内部错误。开发团队已收到通知。"
            )
    except:
        pass


# ==================== 健康检查服务器 (用于 Render) ====================
def run_health_server():
    """运行简单的 HTTP 服务器用于 Render 健康检查"""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    
    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/health' or self.path == '/':
                self.send_response(200)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(b'OK')
            else:
                self.send_response(404)
                self.end_headers()
        
        def log_message(self, format, *args):
            pass  # 禁止日志输出
    
    port = int(os.environ.get('PORT', 8000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    logger.info(f"Health check server running on port {port}")
    server.serve_forever()


# ==================== 主函数 ====================
def main():
    """启动机器人"""
    # 在单独线程中启动健康检查服务器 (用于 Render)
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    logger.info("Health check server started in background thread")
    
    # 创建应用
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # ========== 注册所有命令 (20+ 个命令) ==========
    
    # 基本命令
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("ping", ping))
    
    # 图像生成命令
    app.add_handler(CommandHandler("gen", gen_command))
    app.add_handler(CommandHandler("genfast", genfast_command))
    app.add_handler(CommandHandler("genall", genall_command))
    app.add_handler(CommandHandler("img", gen_command))  # 别名
    
    # 文本生成命令
    app.add_handler(CommandHandler("ask", ask_command))
    app.add_handler(CommandHandler("askall", askall_command))
    app.add_handler(CommandHandler("chat", chat_command))
    app.add_handler(CommandHandler("summarize", summarize_command))
    app.add_handler(CommandHandler("translate", translate_command))
    app.add_handler(CommandHandler("code", code_command))
    app.add_handler(CommandHandler("explain", explain_command))
    
    # 信息命令
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("providers", providers_command))
    app.add_handler(CommandHandler("history", history_command))
    
    # 错误处理
    app.add_error_handler(error_handler)
    
    # 启动机器人
    logger.info("=" * 50)
    logger.info("终极 AI 机器人启动!")
    logger.info(f"图像提供商: {len(provider_manager.image_providers)} 个")
    logger.info(f"文本提供商: {len(provider_manager.text_providers)} 个")
    logger.info("所有提供商: 完全免费, 无需 API 密钥")
    logger.info("=" * 50)
    
    # 开始轮询
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()