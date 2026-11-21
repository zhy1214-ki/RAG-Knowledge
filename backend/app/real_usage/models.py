import httpx
from app.core.errors import AppError
from app.rag.providers import QwenModels, _check_paid_models


class GuardedModels(QwenModels):
    def __init__(self, cfg, guard, client_factory=None):
        super().__init__(cfg)
        self.guard = guard
        self.client_factory = client_factory or httpx.Client

    def call(self, path, body, code):
        _check_paid_models(self.cfg)
        body = dict(body)
        if path == "/chat/completions":
            body.update(max_tokens=self.cfg.max_output_tokens, enable_thinking=False, stream=False)
        expected = self.cfg.embedding_model if path == "/embeddings" else self.cfg.qwen_model
        if body.get("model") != expected:
            raise AppError("MODEL_DISABLED", "模型配置与审核范围不符", 403)
        def send(payload):
            with self.client_factory(timeout=self.cfg.model_timeout_seconds, trust_env=False,
                    follow_redirects=False, transport=httpx.HTTPTransport(retries=0)) as client:
                result = client.post(self.cfg.qwen_base_url + path, json=payload,
                    headers={"Authorization": "Bearer " + self.cfg.dashscope_api_key.get_secret_value()})
                result.raise_for_status()
                return result.json()
        return self.guard.execute(path, body, send, code)

    def embed(self, texts):
        if any(len(text.encode("utf-8")) > self.cfg.max_input_tokens for text in texts):
            raise AppError("TOKEN_LIMIT", "Input exceeds environment limit", 422)
        result, batch, size = [], [], 0
        for text in texts:
            amount = len(text.encode("utf-8"))
            if amount > self.cfg.max_input_tokens:
                raise AppError("TOKEN_LIMIT", "单个片段超过Token估算上限", 422)
            if batch and (len(batch) == 10 or size + amount > self.cfg.max_input_tokens):
                result.extend(self._batch(batch)); batch, size = [], 0
            batch.append(text); size += amount
        if batch: result.extend(self._batch(batch))
        return result

    def _batch(self, batch):
        try:
            return super().embed(batch)
        except AppError as exc:
            if exc.code == "EMBEDDING_ERROR": self.guard.stop("EMBEDDING_RESULT_INVALID")
            raise

    def answer(self, question, sources, history):
        try:
            return super().answer(question, sources, history)
        except AppError as exc:
            if exc.code == "MODEL_UNAVAILABLE": self.guard.stop("ANSWER_RESULT_INVALID")
            raise