import requests
import time
import logging
import posixpath
from typing import List, Optional

logger = logging.getLogger(__name__)


def _is_valid_image_key(value: object) -> bool:
    """Accept only a relative, safe object key for the JPEG being uploaded."""
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    if value.startswith("/") or "\\" in value or "://" in value:
        return False
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return False
    if posixpath.isabs(value):
        return False
    return value.lower().endswith((".jpg", ".jpeg"))


def build_upload_key(snowFlakeId: str, userId: str) -> str:
    """
    生成唯一的文件上传路径。
    
    Args:
        snowFlakeId (str): 用于标识文件唯一性的雪花ID。
        userId (str): 用于标识文件所有者的用户ID。

    Returns:
        str: 生成的文件上传路径。
    """
    return (f"upload/{snowFlakeId}"
            f"/{time.strftime('%Y-%m-%d', time.localtime())}"
            f"/report/{userId}_{int(time.time() * 1000000)}.jpg")


def upload_image(
    session: requests.Session,
    url: str,
    headers: dict,
    image_data: bytes,
    token: str,
    key: str,
    max_retries: int = 3,
    retry_delay: int = 5,
) -> Optional[str]:
    """
    上传单张图片并处理错误。

    Args:
        session (requests.Session): 请求会话。
        url (str): 上传图片的目标URL。
        headers (dict): 请求头信息。
        image_data (bytes): 要上传的图片数据。
        token (str): 用于身份验证的令牌。
        key (str): 上传图片的唯一标识符。
        max_retries (int): 最大重试次数。
        retry_delay (int): 初始重试延迟时间（秒）。

    Returns:
        Optional[str]: 成功上传的图片标识符（去除前缀 "upload/"）。
    """
    data = {
        "token": token,
        "key": key,
        "x-qn-meta-fname": f"{int(time.time() * 1000)}.jpg",
    }

    files = {"file": (key, image_data, "image/jpeg")}

    for attempt in range(max_retries):
        try:
            response = session.post(
                url,
                headers=headers,
                files=files,
                data=data,
                timeout=30
            )
            response.raise_for_status()

            response_data = response.json()
            if not isinstance(response_data, dict):
                logger.warning("上传响应不是有效JSON对象")
                return None
            if response_data.get("error"):
                logger.warning("上传业务失败: %s", response_data.get("error"))
                return None
            if ("code" in response_data and response_data["code"] not in (0, 200, "0", "200")) or response_data.get("success") is False:
                logger.warning("上传响应包含失败的业务状态")
                return None
            returned_key = response_data.get("key")
            if not _is_valid_image_key(returned_key):
                logger.warning("上传响应中的key不是有效图片对象路径")
                return None
            # Preserve the established attachment contract by removing only
            # a leading upload/ prefix, not matching it elsewhere in the key.
            return returned_key[len("upload/"):] if returned_key.startswith("upload/") else returned_key
        except ValueError as e:
            logger.warning("上传响应JSON无效: %s", e)
            return None
        except requests.exceptions.RequestException as e:
            logger.warning(f"上传失败 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                wait_time = retry_delay * (2**attempt)
                time.sleep(wait_time)
            else:
                logger.error(f"上传失败，已达到最大重试次数: {e}")
                return None
    return None


def upload(
    token: str,
    snowFlakeId: str,
    userId: str,
    images: List[bytes],
) -> str:
    """
    上传图片（支持一次性上传多张图片）

    Args:
        token (str): 上传文件的认证令牌。
        snowFlakeId (str): 组织ID。
        userId (str): 用户ID。
        images (List[bytes]): 图片的二进制数据列表。

    Returns:
        str: 成功上传的图片链接，用逗号分隔。
    """
    for field_name, field_value in (
        ("token", token),
        ("snowFlakeId", snowFlakeId),
        ("userId", userId),
    ):
        valid_type = isinstance(field_value, str) if field_name == "token" else isinstance(field_value, (str, int)) and not isinstance(field_value, bool)
        if not valid_type or not str(field_value).strip():
            raise ValueError(f"上传图片失败：{field_name}不能为空")
    url = "https://up.qiniup.com/"
    headers = {
        "host": "up.qiniup.com",
        "accept-encoding": "gzip",
        "user-agent": "Dart / 2.17(dart:io)",
    }

    successful_keys = []

    with requests.Session() as session:
        for image_data in images:
            # 确保每个文件的键唯一，稍微延迟一下或者使用计数器
            # 原代码用微秒级时间戳，基本安全
            key = build_upload_key(snowFlakeId, userId)

            uploaded_key = upload_image(session, url, headers, image_data, token, key)

            if uploaded_key:
                successful_keys.append(uploaded_key)
            
            # 稍微暂停，降低键冲突概率（虽然极低）
            time.sleep(0.01)

    return ",".join(successful_keys)
