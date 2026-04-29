"""Tests for GeminiClassifier — mocks the Gemini API to test parsing/retry/fallback."""
import json
from unittest.mock import MagicMock, patch

import pytest

from tests.conftest import make_email


@pytest.fixture
def fast_classifier():
    """Build classifier sem real API key e SEM pacing/retry delays — só pra testar lógica."""
    from tria.classifiers import gemini

    with patch.object(gemini.genai, "configure"), patch.object(
        gemini.genai, "GenerativeModel"
    ):
        clf = gemini.GeminiClassifier(
            api_key="fake",
            model="gemini-2.5-flash",
            request_pacing_seconds=0,  # sem sleep nos testes
            max_retries=2,
        )
        # Override delays to zero pra testes rodarem rápido
        clf._RETRY_DELAYS = [0, 0, 0, 0]
        return clf


class TestSuccessfulClassification:
    def test_parses_valid_json_response(self, fast_classifier, categories):
        fake_response = MagicMock()
        fake_response.text = json.dumps(
            {"category_id": "important", "reasoning": "Banco notification"}
        )
        fast_classifier.model.generate_content = MagicMock(return_value=fake_response)

        result = fast_classifier.classify(make_email(), categories)

        assert result.success is True
        assert result.category_id == "important"
        assert result.reasoning == "Banco notification"

    def test_strips_whitespace_in_response(self, fast_classifier, categories):
        fake_response = MagicMock()
        fake_response.text = (
            '   {"category_id": "  spam  ", "reasoning": "  promo  "}   '
        )
        fast_classifier.model.generate_content = MagicMock(return_value=fake_response)

        result = fast_classifier.classify(make_email(), categories)
        assert result.category_id == "spam"
        assert result.reasoning == "promo"


class TestInvalidCategoryFallback:
    def test_invalid_category_marks_as_failed(self, fast_classifier, categories):
        """LLM retornou categoria inexistente — não pode virar spam por engano."""
        fake_response = MagicMock()
        fake_response.text = json.dumps(
            {"category_id": "nonsense", "reasoning": "made-up"}
        )
        fast_classifier.model.generate_content = MagicMock(return_value=fake_response)

        result = fast_classifier.classify(make_email(), categories)
        assert result.success is False
        assert result.category_id == ""
        assert "nonsense" in result.reasoning


class TestErrorHandling:
    def test_rate_limit_after_retries_returns_failure(self, fast_classifier, categories):
        """Falha persistente NÃO pode virar spam — tem que sinalizar success=False."""

        class ResourceExhausted(Exception):
            pass

        fast_classifier.model.generate_content = MagicMock(
            side_effect=ResourceExhausted("rate limit")
        )

        result = fast_classifier.classify(make_email(), categories)

        assert result.success is False
        assert result.category_id == ""
        assert "ResourceExhausted" in result.reasoning
        # CRÍTICO: jamais cair em spam por engano
        assert result.category_id != "spam"

    def test_invalid_json_response_marks_as_failed(self, fast_classifier, categories):
        fake_response = MagicMock()
        fake_response.text = "this is not json {[}"
        fast_classifier.model.generate_content = MagicMock(return_value=fake_response)

        result = fast_classifier.classify(make_email(), categories)
        assert result.success is False
        assert result.category_id != "spam"

    def test_non_retryable_error_does_not_retry(self, fast_classifier, categories):
        """Erros não-transientes (ex: ValueError) não fazem retry — falham imediatamente."""

        fast_classifier.model.generate_content = MagicMock(
            side_effect=ValueError("permanent")
        )

        result = fast_classifier.classify(make_email(), categories)
        # Apenas 1 tentativa (sem retry)
        assert fast_classifier.model.generate_content.call_count == 1
        assert result.success is False


class TestRetryLogic:
    def test_retries_on_transient_then_succeeds(self, fast_classifier, categories):
        """Falha transiente seguida de sucesso = classificação válida (não fallback)."""

        class ResourceExhausted(Exception):
            pass

        good_response = MagicMock()
        good_response.text = json.dumps(
            {"category_id": "read_later", "reasoning": "ok depois de retry"}
        )

        # Falha 1x, depois sucesso
        fast_classifier.model.generate_content = MagicMock(
            side_effect=[ResourceExhausted("transient"), good_response]
        )

        result = fast_classifier.classify(make_email(), categories)
        assert result.success is True
        assert result.category_id == "read_later"
        assert fast_classifier.model.generate_content.call_count == 2


class TestPiiRedaction:
    def test_cpf_redacted_before_llm_call(self, fast_classifier, categories):
        """CPF no email NÃO deve chegar no prompt enviado ao Gemini."""
        from tria.classifiers import gemini

        with patch.object(gemini.genai, "configure"), patch.object(
            gemini.genai, "GenerativeModel"
        ):
            clf = gemini.GeminiClassifier(
                api_key="fake",
                redact_patterns=[r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"],
                request_pacing_seconds=0,
                max_retries=1,
            )
            clf._RETRY_DELAYS = [0]

            fake_response = MagicMock()
            fake_response.text = json.dumps(
                {"category_id": "important", "reasoning": "ok"}
            )
            clf.model.generate_content = MagicMock(return_value=fake_response)

            email = make_email(snippet="Meu CPF é 123.456.789-00 confidencial")
            clf.classify(email, categories)

            # Recupera o prompt enviado
            call_args = clf.model.generate_content.call_args[0][0]
            assert "123.456.789-00" not in call_args
            assert "[REDACTED]" in call_args
