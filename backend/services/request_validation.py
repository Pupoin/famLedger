"""Validate legacy wrapped JSON bodies just like typed FastAPI bodies."""
from fastapi import HTTPException
from pydantic import ValidationError
from pydantic import AfterValidator
from typing import Annotated


def validate_currency(value):
    from models import VALID_CURRENCIES
    if value not in VALID_CURRENCIES:
        raise ValueError("不支持的币种")
    return value


CurrencyCode = Annotated[str, AfterValidator(validate_currency)]


async def parse_body(request, model, wrapper=None):
    try:
        data = await request.json()
        if not isinstance(data, dict):
            raise HTTPException(422, "请求体必须是 JSON 对象")
        return model.model_validate(data.get(wrapper, data) if wrapper else data)
    except (ValueError, ValidationError) as exc:
        detail = exc.errors(include_context=False) if isinstance(exc, ValidationError) else "无效的 JSON 请求体"
        raise HTTPException(422, detail=detail)
