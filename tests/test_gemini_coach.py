import json
import re
import tempfile
import unittest
from email.message import Message
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch
from urllib.error import HTTPError, URLError

from smart_money_hub_bot.bot import SmartMoneyHubBot
from smart_money_hub_bot.coach import CoachProviderError, RuleBasedCoachService
from smart_money_hub_bot.gemini_coach import (
    GEMINI_ENDPOINT,
    GEMINI_FALLBACK_MODELS,
    GEMINI_MODEL,
    GeminiCoachService,
)
from smart_money_hub_bot.message_router import CoachMessageRouter
from smart_money_hub_bot.telegram_api import TelegramAPI


def _http_response(body: bytes) -> MagicMock:
    response = MagicMock()
    response.status = 200
    response.headers = Message()
    response.__enter__.return_value.status = 200
    response.__enter__.return_value.headers = Message()
    response.__enter__.return_value.read.return_value = body
    return response


def _response(
    answer: str,
    needs_review: bool = False,
    *,
    usage_metadata: dict | None = None,
) -> MagicMock:
    data = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "answer": answer,
                                    "needs_review": needs_review,
                                }
                            )
                        }
                    ]
                },
                "finishReason": "STOP",
            }
        ]
    }
    if usage_metadata is not None:
        data["usageMetadata"] = usage_metadata
    return _http_response(json.dumps(data).encode("utf-8"))


def _provider_response(data: dict) -> MagicMock:
    return _http_response(json.dumps(data).encode("utf-8"))


def _provider_error(
    status_code: int,
    provider_status: str,
    message: str,
    *,
    headers: dict[str, str] | None = None,
) -> HTTPError:
    response_headers = Message()
    for name, value in (headers or {}).items():
        response_headers[name] = value
    body = json.dumps(
        {
            "error": {
                "code": status_code,
                "status": provider_status,
                "message": message,
            }
        }
    ).encode("utf-8")
    return HTTPError(
        GEMINI_ENDPOINT,
        status_code,
        "provider error",
        response_headers,
        BytesIO(body),
    )


def _raise_provider_error(
    status_code: int,
    provider_status: str,
    message: str,
    *,
    headers: dict[str, str] | None = None,
) -> None:
    raise _provider_error(
        status_code, provider_status, message, headers=headers
    )


class _EmptyKnowledgeStore:
    def approved_knowledge_items(self):
        return []


class _UncertainService:
    def evaluate(self, message, *, history=None, profile=None, request_id=None):
        from smart_money_hub_bot.coach import CoachReply

        return CoachReply(
            "I am not certain about this yet.",
            "BOS",
            (),
            "",
            requires_review=True,
        )


class GeminiCoachTests(unittest.TestCase):
    def test_missing_key_falls_back_without_attempting_a_network_request(self) -> None:
        service = GeminiCoachService("")
        router = CoachMessageRouter(service, _EmptyKnowledgeStore())
        routed = router.route(321, "What is BOS?")
        reply = routed.reply
        self.assertEqual(reply.detected_topic, "BOS")
        self.assertIn("Break of Structure", reply.response)
        self.assertEqual(routed.response_path, "fallback")

    def test_gemini_response_uses_fixed_free_model_and_key_header(self) -> None:
        service = GeminiCoachService("test-secret-value")
        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen",
            return_value=_response("A BOS is a break through a relevant swing."),
        ) as mocked_urlopen:
            reply = service.evaluate("What is BOS?")

        request = mocked_urlopen.call_args.args[0]
        headers = {key.casefold(): value for key, value in request.header_items()}
        self.assertEqual(GEMINI_MODEL, "gemini-3.5-flash-lite")
        self.assertEqual(request.full_url, GEMINI_ENDPOINT)
        self.assertEqual(headers["x-goog-api-key"], "test-secret-value")
        self.assertNotIn("test-secret-value", request.full_url)
        self.assertIn("relevant swing", reply.response)
        self.assertEqual(reply.detected_topic, "BOS")
        self.assertFalse(reply.requires_review)
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(
            payload["generationConfig"]["responseMimeType"], "application/json"
        )
        self.assertEqual(
            payload["generationConfig"]["thinkingConfig"],
            {"thinkingLevel": "LOW"},
        )
        self.assertEqual(payload["generationConfig"]["maxOutputTokens"], 1024)
        self.assertEqual(mocked_urlopen.call_count, 1)

    def test_rate_limit_fails_over_with_same_member_context(self) -> None:
        service = GeminiCoachService("test-key")
        question = "Explain liquidity using my earlier Gold example."
        history = [
            {
                "question": "I am studying Gold structure.",
                "coach_response": "We discussed swing highs and lows.",
            }
        ]
        fallback_answer = "Liquidity is a pool of resting orders near obvious levels."
        request_id = "a" * 32
        rate_limit = _provider_error(
            429, "RESOURCE_EXHAUSTED", "Quota temporarily exhausted."
        )

        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen",
            side_effect=[rate_limit, _response(fallback_answer)],
        ) as mocked_urlopen, self.assertLogs(
            "smart_money_hub_bot", level="INFO"
        ) as logs:
            reply = service.evaluate(
                question, history=history, request_id=request_id
            )

        self.assertEqual(reply.response, fallback_answer)
        self.assertEqual(mocked_urlopen.call_count, 2)
        requests = [
            call.args[0] for call in mocked_urlopen.call_args_list
        ]
        self.assertEqual(
            [request.full_url for request in requests],
            [
                GEMINI_ENDPOINT,
                (
                    "https://generativelanguage.googleapis.com/v1beta/models/"
                    f"{GEMINI_FALLBACK_MODELS[0]}:generateContent"
                ),
            ],
        )
        payloads = [
            json.loads(request.data.decode("utf-8")) for request in requests
        ]
        self.assertEqual(payloads[0]["contents"], payloads[1]["contents"])
        self.assertEqual(
            payloads[0]["systemInstruction"],
            payloads[1]["systemInstruction"],
        )
        self.assertEqual(
            payloads[0]["generationConfig"]["responseMimeType"],
            payloads[1]["generationConfig"]["responseMimeType"],
        )
        self.assertEqual(
            payloads[0]["generationConfig"]["thinkingConfig"],
            {"thinkingLevel": "LOW"},
        )
        self.assertEqual(
            payloads[1]["generationConfig"]["thinkingConfig"],
            {"thinkingLevel": "MINIMAL"},
        )
        self.assertIn(f"request_id={request_id}", "\n".join(logs.output))
        self.assertIn(GEMINI_FALLBACK_MODELS[0], "\n".join(logs.output))
        self.assertNotIn(question, "\n".join(logs.output))
        self.assertNotIn(fallback_answer, "\n".join(logs.output))

    def test_missing_model_fails_over_to_next_configured_model(self) -> None:
        service = GeminiCoachService("test-key")
        not_found = _provider_error(
            404, "NOT_FOUND", "Requested model is unavailable."
        )
        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen",
            side_effect=[not_found, _response("Fallback model answered.")],
        ) as mocked_urlopen:
            reply = service.evaluate("What is a fair value gap?")

        self.assertEqual(reply.response, "Fallback model answered.")
        self.assertEqual(mocked_urlopen.call_count, 2)
        self.assertIn(
            GEMINI_FALLBACK_MODELS[0],
            mocked_urlopen.call_args_list[1].args[0].full_url,
        )

    def test_plain_text_candidate_parts_are_returned_without_json_decoding(self) -> None:
        service = GeminiCoachService("test-key")
        router = CoachMessageRouter(service, _EmptyKnowledgeStore())
        response = _provider_response(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "A BOS breaks a relevant swing. "},
                                {"text": "It can support continuation."},
                                {"text": "private thought", "thought": True},
                            ]
                        },
                        "finishReason": "STOP",
                    }
                ]
            }
        )

        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen", return_value=response
        ), self.assertLogs("smart_money_hub_bot", level="INFO") as logs:
            routed = router.route(321, "What is BOS?")

        self.assertEqual(
            routed.reply.response,
            "A BOS breaks a relevant swing. It can support continuation.",
        )
        self.assertFalse(routed.reply.requires_review)
        self.assertEqual(routed.response_path, "gemini_success")
        joined_logs = "\n".join(logs.output)
        self.assertNotIn("A BOS breaks a relevant swing", joined_logs)
        self.assertNotIn("private thought", joined_logs)
        self.assertNotIn("test-key", joined_logs)

    def test_candidate_without_optional_finish_reason_is_accepted(self) -> None:
        service = GeminiCoachService("test-key")
        response = _provider_response(
            {
                "candidates": [
                    {
                        "content": {"parts": [{"text": "Liquidity is resting orders."}]}
                    }
                ]
            }
        )

        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen", return_value=response
        ):
            reply = service.evaluate("What is liquidity?")

        self.assertEqual(reply.response, "Liquidity is resting orders.")

    def test_structured_answer_is_preserved_when_review_flag_is_omitted(self) -> None:
        service = GeminiCoachService("test-key")
        response = _provider_response(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {"answer": "An FVG is an imbalance."}
                                    )
                                }
                            ]
                        },
                        "finishReason": "STOP",
                    }
                ]
            }
        )

        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen", return_value=response
        ):
            reply = service.evaluate("What is an FVG?")

        self.assertEqual(reply.response, "An FVG is an imbalance.")
        self.assertFalse(reply.requires_review)

    def test_truncated_and_blocked_finish_reasons_are_rejected_safely(self) -> None:
        cases = (
            ("MAX_TOKENS", "incomplete_response"),
            ("SAFETY", "blocked_response"),
            ("RECITATION", "blocked_response"),
        )
        for finish_reason, failure_kind in cases:
            with self.subTest(finish_reason=finish_reason):
                service = GeminiCoachService("test-key")
                response = _provider_response(
                    {
                        "candidates": [
                            {
                                "content": {
                                    "parts": [{"text": "partial answer"}]
                                },
                                "finishReason": finish_reason,
                            }
                        ]
                    }
                )
                with patch(
                    "smart_money_hub_bot.gemini_coach.urlopen",
                    return_value=response,
                ):
                    with self.assertRaises(CoachProviderError) as caught:
                        service.evaluate("What is liquidity?")
                self.assertEqual(caught.exception.failure_kind, failure_kind)
                self.assertEqual(caught.exception.provider_status, finish_reason)
                self.assertEqual(
                    caught.exception.rejection_category, "finish_reason_rejected"
                )

    def test_max_tokens_logs_safe_usage_and_uses_fallback(self) -> None:
        router = CoachMessageRouter(
            GeminiCoachService("test-key"), _EmptyKnowledgeStore()
        )
        request_id = "a" * 32
        response = _provider_response(
            {
                "candidates": [
                    {
                        "content": {"parts": [{"text": "partial answer must not leak"}]},
                        "finishReason": "MAX_TOKENS",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 123,
                    "candidatesTokenCount": 1024,
                    "thoughtsTokenCount": 840,
                    "totalTokenCount": 1147,
                    "unsafe_extra": "not logged",
                },
            }
        )

        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen", return_value=response
        ), self.assertLogs("smart_money_hub_bot", level="INFO") as logs:
            routed = router.route(
                321,
                "What is liquidity?",
                request_id=request_id,
            )

        joined_logs = "\n".join(logs.output)
        self.assertEqual(routed.response_path, "fallback")
        self.assertEqual(routed.request_id, request_id)
        self.assertIn("finish_reason=MAX_TOKENS", joined_logs)
        self.assertIn("max_output_tokens=1024", joined_logs)
        self.assertIn("'candidate_tokens': 1024", joined_logs)
        self.assertIn("'thought_tokens': 840", joined_logs)
        self.assertIn("rejection_category=finish_reason_rejected", joined_logs)
        self.assertNotIn("partial answer must not leak", joined_logs)
        self.assertNotIn("unsafe_extra", joined_logs)

    def test_prompt_block_and_empty_or_malformed_responses_fail_safely(self) -> None:
        cases = (
            (
                _provider_response(
                    {"promptFeedback": {"blockReason": "SAFETY"}}
                ),
                "blocked_response",
            ),
            (_provider_response({"candidates": []}), "invalid_response"),
            (
                _provider_response(
                    {
                        "candidates": [
                            {"content": {"parts": [{"inlineData": {"data": "x"}}]}}
                        ]
                    }
                ),
                "invalid_response",
            ),
            (_http_response(b"{malformed"), "invalid_response"),
        )
        for response, failure_kind in cases:
            with self.subTest(failure_kind=failure_kind):
                service = GeminiCoachService("test-key")
                with patch(
                    "smart_money_hub_bot.gemini_coach.urlopen",
                    return_value=response,
                ):
                    with self.assertRaises(CoachProviderError) as caught:
                        service.evaluate("What is liquidity?")
                self.assertEqual(caught.exception.failure_kind, failure_kind)
                self.assertIsNotNone(caught.exception.rejection_category)

    def test_empty_candidate_response_uses_local_fallback(self) -> None:
        router = CoachMessageRouter(
            GeminiCoachService("test-key"), _EmptyKnowledgeStore()
        )
        response = _provider_response({"candidates": []})

        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen", return_value=response
        ):
            routed = router.route(321, "What is liquidity?")

        self.assertEqual(routed.response_path, "fallback")
        self.assertIn("liquidity", routed.reply.response.casefold())

    def test_conversation_context_is_bounded_and_isolated_per_member(self) -> None:
        service = GeminiCoachService("test-key")
        history_a = [
            {"question": "Alice-only coaching detail", "coach_response": "Alice reply"}
        ]
        history_b = [
            {"question": "Bob-only coaching detail", "coach_response": "Bob reply"}
        ]
        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen",
            side_effect=[_response("Answer A"), _response("Answer B")],
        ) as mocked_urlopen:
            service.evaluate("What is BOS?", history=history_a)
            service.evaluate("What is CHoCH?", history=history_b)

        payloads = [
            json.loads(call.args[0].data.decode("utf-8"))
            for call in mocked_urlopen.call_args_list
        ]
        first = json.dumps(payloads[0])
        second = json.dumps(payloads[1])
        self.assertIn("Alice-only coaching detail", first)
        self.assertNotIn("Bob-only coaching detail", first)
        self.assertIn("Bob-only coaching detail", second)
        self.assertNotIn("Alice-only coaching detail", second)
        self.assertNotIn("telegram_id", first.casefold())
        self.assertNotIn("telegram_id", second.casefold())

    def test_standalone_educational_question_does_not_receive_old_context(self) -> None:
        question = (
            "What is the difference between BOS and CHOCH? Explain it simply "
            "with a practical Gold chart example."
        )
        old_history = [
            {
                "question": "I chased after displacement and felt FOMO.",
                "coach_response": "What rule will help you avoid chasing next time?",
                "detected_topic": "FOMO",
            }
        ]
        old_profile = {"learning_goal": "Avoid FOMO and wait for a retest"}
        service = GeminiCoachService("test-key")
        router = CoachMessageRouter(service, _EmptyKnowledgeStore())

        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen",
            return_value=_response(
                "A BOS breaks a key swing in the current direction; a CHOCH is a "
                "break against it. Bullish Gold example: after lower highs, a close "
                "above a lower high may signal a bullish shift. Bearish Gold example: "
                "after higher lows, a close below a higher low may signal a bearish "
                "shift. CHOCH is a possible shift, not a guaranteed reversal. Which "
                "swing are you studying?"
            ),
        ) as mocked_urlopen:
            routed = router.route(
                321, question, history=old_history, profile=old_profile
            )

        payload = json.loads(mocked_urlopen.call_args.args[0].data.decode("utf-8"))
        contents = payload["contents"]
        self.assertEqual(
            contents,
            [{"role": "user", "parts": [{"text": question}]}],
        )
        payload_text = json.dumps(payload).casefold()
        self.assertNotIn("fomo", payload_text)
        self.assertNotIn("avoid fomo", payload_text)
        self.assertEqual(routed.response_path, "gemini_success")
        self.assertIn("hypothetical bullish", payload["systemInstruction"]["parts"][0]["text"])
        self.assertIn("hypothetical bearish", payload["systemInstruction"]["parts"][0]["text"])

    def test_hypothetical_choch_scenario_uses_given_facts_and_answers_each_part(self) -> None:
        question = (
            "Hypothetically, Gold has a bearish H1 bias. On M5, price sweeps BSL, "
            "closes below the prior higher low with bearish displacement, then "
            "retests that level. I have not entered. Explain whether this is a CHOCH, "
            "what displacement and the retest add, where invalidation and the stop "
            "belong, and how to assess risk and planned R:R."
        )
        answer = (
            "1. If the prior M5 sequence was higher lows, a close below the prior "
            "higher low after the BSL sweep can be a bearish CHOCH; it signals a "
            "possible shift, not a guaranteed reversal.\n"
            "2. The bearish displacement adds evidence of intent but is not proof.\n"
            "3. The stated retest can provide an entry opportunity in a model that "
            "uses retests; other models may use a different trigger.\n"
            "4. Invalidate the idea where its structural premise fails and place the "
            "stop from that level; no exact price is available from the text.\n"
            "5. Apply the configured H1/M5 plan, 2% risk per trade, minimum 1:3 "
            "planned R:R, 3% daily loss limit, and break-even at 1:1. These rules do "
            "not guarantee a valid trade."
        )
        router = CoachMessageRouter(
            GeminiCoachService("test-key"), _EmptyKnowledgeStore()
        )
        old_history = [
            {
                "question": "I chased after displacement and felt FOMO.",
                "coach_response": "Did you follow your plan?",
                "detected_topic": "FOMO",
            }
        ]

        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen",
            return_value=_response(answer),
        ) as mocked_urlopen:
            routed = router.route(324, question, history=old_history)

        payload = json.loads(mocked_urlopen.call_args.args[0].data.decode("utf-8"))
        instruction = payload["systemInstruction"]["parts"][0]["text"].casefold()
        self.assertEqual(routed.response_path, "gemini_success")
        self.assertEqual(routed.reply.response, answer)
        self.assertEqual(
            payload["contents"],
            [{"role": "user", "parts": [{"text": question}]}],
        )
        self.assertIn("classified as hypothetical_scenario", instruction)
        self.assertIn("answer each requested point directly", instruction)
        self.assertIn("do not ask for", instruction)
        self.assertIn("not by every model", instruction)
        self.assertIn("minimum 1:3 planned r:r", instruction)
        self.assertIn("for a single-concept question, be concise", instruction)
        self.assertIn("concise numbered walkthrough", instruction)
        self.assertIn("do not merely list terms", instruction)
        self.assertNotIn("keep answer brief", instruction)
        self.assertNotIn("did you follow your plan", json.dumps(payload).casefold())
        self.assertNotIn("which swing level broke", routed.reply.response.casefold())
        self.assertNotIn("from what you wrote, review", routed.reply.response.casefold())

    def test_rate_limited_hypothetical_fallback_explains_each_setup_step(self) -> None:
        question = (
            "Hypothetically, Gold has a bullish H1 bias at an H1 demand zone. On M5, "
            "price swept sell-side liquidity below prior lows, then bullish displacement "
            "closed above the last M5 lower high, forming a bullish CHOCH. Explain how "
            "the context, sweep, displacement and CHOCH connect; whether to wait for a "
            "retest; where invalidation and the stop belong; and how to manage risk and "
            "planned R:R."
        )
        router = CoachMessageRouter(
            GeminiCoachService("test-key"), _EmptyKnowledgeStore()
        )

        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen",
            side_effect=lambda *_args, **_kwargs: _raise_provider_error(
                429, "RESOURCE_EXHAUSTED", "Quota exceeded."
            ),
        ):
            routed = router.route(324, question)

        answer = routed.reply.response.casefold()
        self.assertEqual(routed.response_path, "fallback")
        self.assertIn("1. h1 context:", answer)
        self.assertIn("not an entry signal by itself", answer)
        self.assertIn("2. m5 liquidity sweep:", answer)
        self.assertIn("sweep below prior lows took sell-side liquidity", answer)
        self.assertIn("3. displacement:", answer)
        self.assertIn("closes through a meaningful swing", answer)
        self.assertIn("4. choch:", answer)
        self.assertIn("possible short-term shift", answer)
        self.assertIn("5. confirmation and standing aside:", answer)
        self.assertIn("skipping preserves the plan", answer)
        self.assertIn("6. retest and entry:", answer)
        self.assertIn("not mandatory for every model", answer)
        self.assertIn("7. invalidation and stop:", answer)
        self.assertIn("8. risk plan:", answer)
        self.assertIn("2% risk per trade", answer)
        self.assertIn("minimum 1:3 planned r:r", answer)
        self.assertIn("compare the planned target with that risk", answer)
        self.assertIn("no exact chart price to calculate", answer)
        self.assertIn("not proof that the setup is valid", answer)

    def test_current_message_is_not_truncated_at_history_turn_limit(self) -> None:
        message = (
            "Hypothetically, explain this setup. "
            + "H1 bias and M5 confirmation details. " * 50
            + "Final requested point: explain where invalidation belongs."
        )
        contents = GeminiCoachService._contents(message, [])

        self.assertGreater(len(message), 1200)
        self.assertEqual(contents[-1]["parts"][0]["text"], message)

    def test_incomplete_bos_choch_generation_uses_complete_local_fallback(self) -> None:
        service = GeminiCoachService("test-key")
        router = CoachMessageRouter(service, _EmptyKnowledgeStore())

        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen",
            return_value=_response("CHOCH may signal a change in trend."),
        ), self.assertLogs("smart_money_hub_bot", level="WARNING") as logs:
            routed = router.route(
                322, "What is the difference between BOS and CHOCH?"
            )

        self.assertEqual(routed.response_path, "fallback")
        self.assertIn(
            "rejection_category=bos_choch_completeness_check_failed",
            "\n".join(logs.output),
        )
        self.assertIn("A BOS (Break of Structure)", routed.reply.response)
        self.assertIn("A CHOCH (Change of Character)", routed.reply.response)
        self.assertIn("Bullish Gold example", routed.reply.response)
        self.assertIn("Bearish Gold example", routed.reply.response)
        self.assertIn("not a guaranteed reversal", routed.reply.response)
        self.assertEqual(routed.reply.response.count("?"), 1)

    def test_valid_plain_text_bos_choch_paraphrase_is_accepted(self) -> None:
        answer = (
            "A Break of Structure (BOS) confirms direction when price breaks a key "
            "swing; a Change of Character (CHOCH) warns the swing sequence may be "
            "changing. Bullish XAUUSD example: after lower highs, a close above the "
            "last lower high can point to a potential upside turn. Bearish XAUUSD "
            "example: after higher lows, a close below the last higher low may "
            "indicate a possible downside change. This is not proof or a guaranteed "
            "reversal; price can resume its prior move. Which timeframe are you "
            "reviewing?"
        )
        router = CoachMessageRouter(
            GeminiCoachService("test-key"), _EmptyKnowledgeStore()
        )

        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen",
            return_value=_provider_response(
                {
                    "candidates": [
                        {
                            "content": {"parts": [{"text": answer}]},
                            "finishReason": "STOP",
                        }
                    ]
                }
            ),
        ):
            routed = router.route(
                323, "What is the difference between BOS and CHOCH on XAUUSD?"
            )

        self.assertEqual(routed.response_path, "gemini_success")
        self.assertEqual(routed.reply.response, answer)

    def test_schema_mismatch_category_is_logged_without_response_content(self) -> None:
        router = CoachMessageRouter(
            GeminiCoachService("test-key"), _EmptyKnowledgeStore()
        )
        private_response_text = "synthetic generated text must not enter logs"
        response = _provider_response(
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {"unexpected": private_response_text}
                                    )
                                }
                            ]
                        },
                        "finishReason": "STOP",
                    }
                ]
            }
        )

        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen", return_value=response
        ), self.assertLogs("smart_money_hub_bot", level="WARNING") as logs:
            routed = router.route(324, "What is liquidity?")

        joined_logs = "\n".join(logs.output)
        self.assertEqual(routed.response_path, "fallback")
        self.assertIn("rejection_category=schema_mismatch", joined_logs)
        self.assertNotIn(private_response_text, joined_logs)

    def test_genuine_follow_ups_keep_only_the_current_members_history(self) -> None:
        service = GeminiCoachService("test-key")
        router = CoachMessageRouter(service, _EmptyKnowledgeStore())
        history_a = [
            {
                "question": "What happened at the CHOCH level?",
                "coach_response": "Which swing high did Gold close above?",
                "detected_topic": "CHoCH",
            },
            {
                "question": "I chased after displacement and felt FOMO.",
                "coach_response": "What rule will help you avoid FOMO?",
                "detected_topic": "FOMO",
            },
        ]
        history_b = [
            {
                "question": "How did I manage the FVG trade?",
                "coach_response": "Did you wait for your retest?",
                "detected_topic": "FVG / IFVG",
            },
            {
                "question": "What is CHOCH?",
                "coach_response": "Which swing level broke?",
                "detected_topic": "CHoCH",
            },
        ]

        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen",
            side_effect=[
                _response("That swing high could be the confirmation level."),
                _response("The retest is the next thing to review."),
            ],
        ) as mocked_urlopen:
            router.route(401, "The 15m high.", history=history_a)
            router.route(402, "The 15m retest.", history=history_b)

        payloads = [
            json.loads(call.args[0].data.decode("utf-8"))
            for call in mocked_urlopen.call_args_list
        ]
        payload_a = json.dumps(payloads[0])
        payload_b = json.dumps(payloads[1])
        self.assertIn("What happened at the CHOCH level?", payload_a)
        self.assertIn("Which swing high did Gold close above?", payload_a)
        self.assertNotIn("FVG trade", payload_a)
        self.assertNotIn("FOMO", payload_a)
        self.assertIn("How did I manage the FVG trade?", payload_b)
        self.assertIn("Did you wait for your retest?", payload_b)
        self.assertNotIn("CHOCH level", payload_b)
        self.assertNotIn("What is CHOCH?", payload_b)

    def test_quota_error_is_sanitized_and_router_falls_back_locally(self) -> None:
        service = GeminiCoachService("do-not-log-this-key")
        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen",
            side_effect=lambda *_args, **_kwargs: _raise_provider_error(
                429, "RESOURCE_EXHAUSTED", "Quota exceeded."
            ),
        ) as mocked_urlopen, patch("smart_money_hub_bot.gemini_coach.time.sleep") as sleep:
            with self.assertRaises(CoachProviderError) as caught:
                service.evaluate("What is BOS?")
            router = CoachMessageRouter(service, _EmptyKnowledgeStore())
            reply = router.route(123, "What is BOS?").reply
        self.assertEqual(
            mocked_urlopen.call_count, 2 * (len(GEMINI_FALLBACK_MODELS) + 1)
        )
        sleep.assert_not_called()
        self.assertEqual(caught.exception.failure_kind, "rate_limit")
        self.assertEqual(caught.exception.status_code, 429)
        self.assertEqual(caught.exception.provider_status, "RESOURCE_EXHAUSTED")
        self.assertEqual(
            caught.exception.provider_message,
            "Google reports a rate limit or quota restriction.",
        )
        self.assertIsNotNone(caught.exception.elapsed_ms)
        self.assertNotIn("do-not-log-this-key", str(caught.exception))
        self.assertEqual(reply.detected_topic, "BOS")
        self.assertIn("Break of Structure", reply.response)

    def test_service_unavailable_falls_back_locally(self) -> None:
        service = GeminiCoachService("test-key")
        router = CoachMessageRouter(service, _EmptyKnowledgeStore())
        api_errors = [
            _provider_error(
                503,
                "UNAVAILABLE",
                "The model is overloaded. Prompt: What is BOS?",
                headers={
                    "Date": "Thu, 22 Oct 2026 08:00:00 GMT",
                    "Retry-After": "0",
                    "Content-Type": "application/json",
                    "X-Private-Diagnostic": "must-not-be-logged",
                },
            ),
            _provider_error(
                503,
                "UNAVAILABLE",
                "The model is overloaded. Prompt: What is BOS?",
                headers={"Retry-After": "3"},
            ),
            _provider_error(
                503,
                "UNAVAILABLE",
                "The model is overloaded. Prompt: What is BOS?",
                headers={"Retry-After": "3"},
            ),
            _provider_error(
                503,
                "UNAVAILABLE",
                "The model is overloaded. Prompt: What is BOS?",
                headers={"Retry-After": "3"},
            ),
        ]
        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen", side_effect=api_errors
        ) as mocked_urlopen, patch(
            "smart_money_hub_bot.gemini_coach.time.sleep"
        ) as sleep, self.assertLogs("smart_money_hub_bot", level="WARNING") as logs:
            routed = router.route(124, "What is BOS?")
        reply = routed.reply
        self.assertEqual(mocked_urlopen.call_count, 4)
        sleep.assert_called_once_with(0.0)
        self.assertIn("Break of Structure", reply.response)
        self.assertEqual(routed.response_path, "fallback")
        joined_logs = "\n".join(logs.output)
        self.assertIn("http_status=503", joined_logs)
        self.assertIn("google_status=UNAVAILABLE", joined_logs)
        self.assertIn(
            "Google reports the generation service is temporarily unavailable.",
            joined_logs,
        )
        self.assertIn("retry-after", joined_logs)
        self.assertNotIn("Prompt: What is BOS?", joined_logs)
        self.assertNotIn("must-not-be-logged", joined_logs)
        self.assertNotIn("test-key", joined_logs)

    def test_bos_vs_choch_educational_question_reaches_gemini(self) -> None:
        question = (
            "What is the difference between a Break of Structure (BOS) and a "
            "Change of Character (CHOCH)? Explain it simply with a practical "
            "Gold chart example."
        )
        generated_answer = (
            "A BOS breaks a key swing in the current direction; a CHOCH is a "
            "break against the current swing sequence. Bullish Gold example: "
            "after lower highs, a close above a prior lower high may signal a "
            "bullish shift. Bearish Gold example: after higher lows, a close "
            "below a prior higher low may signal a bearish shift. A CHOCH is a "
            "possible shift, not a guaranteed reversal. Which swing level are "
            "you studying?"
        )
        service = GeminiCoachService("test-key")
        router = CoachMessageRouter(service, _EmptyKnowledgeStore())

        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen",
            return_value=_response(generated_answer),
        ) as mocked_urlopen:
            routed = router.route(124, question)

        self.assertEqual(mocked_urlopen.call_count, 1)
        self.assertEqual(routed.response_path, "gemini_success")
        self.assertEqual(routed.reply.response, generated_answer)
        self.assertIsNotNone(routed.assessment)
        self.assertEqual(routed.assessment.confidence, "high")
        payload = json.loads(mocked_urlopen.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(payload["contents"][-1]["parts"][0]["text"], question)

    def test_bos_vs_choch_provider_failure_uses_local_fallback(self) -> None:
        service = GeminiCoachService("test-key")
        router = CoachMessageRouter(service, _EmptyKnowledgeStore())
        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen",
            side_effect=lambda *_args, **_kwargs: _raise_provider_error(
                503,
                "UNAVAILABLE",
                "The service is temporarily unavailable.",
                headers={"Retry-After": "3"},
            ),
        ) as mocked_urlopen:
            routed = router.route(
                125, "What is the difference between BOS and CHOCH?"
            )

        self.assertEqual(mocked_urlopen.call_count, len(GEMINI_FALLBACK_MODELS) + 1)
        self.assertEqual(routed.response_path, "fallback")
        self.assertIsNotNone(routed.assessment)
        self.assertEqual(routed.assessment.confidence, "high")
        self.assertIn("A BOS (Break of Structure)", routed.reply.response)
        self.assertIn("A CHOCH (Change of Character)", routed.reply.response)
        self.assertIn("Bullish Gold example", routed.reply.response)
        self.assertIn("Bearish Gold example", routed.reply.response)
        self.assertIn("not a guaranteed reversal", routed.reply.response)
        self.assertEqual(routed.reply.response.count("?"), 1)

    def test_single_503_retry_succeeds_within_existing_deadline(self) -> None:
        service = GeminiCoachService("test-key", timeout_seconds=3)
        first_error = _provider_error(
            503, "UNAVAILABLE", "The model is overloaded."
        )
        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen",
            side_effect=[first_error, _response("Recovered after one retry.")],
        ) as mocked_urlopen, patch(
            "smart_money_hub_bot.gemini_coach.time.sleep"
        ) as sleep:
            reply = service.evaluate("What is liquidity?")

        self.assertEqual(reply.response, "Recovered after one retry.")
        self.assertEqual(mocked_urlopen.call_count, 2)
        sleep.assert_called_once_with(0.25)
        first_timeout = mocked_urlopen.call_args_list[0].kwargs["timeout"]
        second_timeout = mocked_urlopen.call_args_list[1].kwargs["timeout"]
        self.assertLessEqual(first_timeout, 3)
        self.assertLessEqual(second_timeout, first_timeout)
        self.assertGreater(second_timeout, 0)

    def test_timeout_uses_the_local_fallback(self) -> None:
        service = GeminiCoachService("test-key")
        router = CoachMessageRouter(service, _EmptyKnowledgeStore())
        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen",
            side_effect=TimeoutError("request timeout"),
        ), self.assertLogs("smart_money_hub_bot", level="WARNING") as logs:
            routed = router.route(456, "Explain break of structure")
        self.assertEqual(routed.reply.detected_topic, "BOS")
        self.assertIn("Break of Structure", routed.reply.response)
        self.assertEqual(routed.response_path, "fallback")
        self.assertIn("kind=client_timeout", "\n".join(logs.output))

    def test_network_failure_attempts_each_model_once(self) -> None:
        service = GeminiCoachService("test-key")
        router = CoachMessageRouter(service, _EmptyKnowledgeStore())
        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen",
            side_effect=URLError("temporary DNS failure"),
        ) as mocked_urlopen, self.assertLogs(
            "smart_money_hub_bot", level="WARNING"
        ) as logs:
            routed = router.route(457, "What is liquidity?")

        self.assertEqual(mocked_urlopen.call_count, len(GEMINI_FALLBACK_MODELS) + 1)
        attempted_urls = [
            call.args[0].full_url for call in mocked_urlopen.call_args_list
        ]
        self.assertEqual(len(attempted_urls), len(set(attempted_urls)))
        self.assertEqual(routed.response_path, "fallback")
        self.assertIn("kind=network", "\n".join(logs.output))

    def test_authentication_and_http_timeout_errors_are_distinct(self) -> None:
        cases = (
            (401, "UNAUTHENTICATED", "Invalid API key.", "authentication"),
            (504, "DEADLINE_EXCEEDED", "Gateway timed out.", "http_timeout"),
        )
        for status_code, provider_status, message, expected_kind in cases:
            with self.subTest(status_code=status_code):
                service = GeminiCoachService("test-key")
                with patch(
                    "smart_money_hub_bot.gemini_coach.urlopen",
                    side_effect=lambda *_args, **_kwargs: _raise_provider_error(
                        status_code, provider_status, message
                    ),
                ) as mocked_urlopen:
                    with self.assertRaises(CoachProviderError) as caught:
                        service.evaluate("What is BOS?")
                self.assertEqual(caught.exception.failure_kind, expected_kind)
                self.assertEqual(caught.exception.status_code, status_code)
                expected_attempts = (
                    1 if status_code == 401 else len(GEMINI_FALLBACK_MODELS) + 1
                )
                self.assertEqual(mocked_urlopen.call_count, expected_attempts)

    def test_ai_uncertainty_is_marked_for_admin_review(self) -> None:
        router = CoachMessageRouter(_UncertainService(), _EmptyKnowledgeStore())
        routed = router.route(789, "What is BOS?")
        self.assertIsNotNone(routed.assessment)
        self.assertEqual(routed.assessment.confidence, "low")
        self.assertTrue(routed.assessment.needs_research)
        self.assertIn("flagged", routed.reply.response)
        self.assertEqual(routed.response_path, "fallback")

    def test_simple_and_unvetted_messages_do_not_call_the_gemini_provider(self) -> None:
        provider = Mock()
        router = CoachMessageRouter(provider, _EmptyKnowledgeStore())
        self.assertEqual(router.route(987, "Hi").intent, "greeting")
        self.assertEqual(router.route(987, "Thanks").response_path, "local_response")
        unknown = router.route(987, "What is the latest inflation report today?")
        self.assertTrue(unknown.assessment.needs_research)
        provider.evaluate.assert_not_called()
        self.assertEqual(unknown.response_path, "local_response")

    def test_unvetted_educational_question_reaches_gemini(self) -> None:
        question = "What does SMT divergence mean in trading?"
        answer = (
            "SMT divergence compares related markets for different swing behavior. "
            "It can suggest relative weakness or strength, but is not an entry signal alone."
        )
        service = GeminiCoachService("test-key")
        router = CoachMessageRouter(service, _EmptyKnowledgeStore())
        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen",
            return_value=_response(answer),
        ) as mocked_urlopen:
            routed = router.route(988, question)

        self.assertEqual(mocked_urlopen.call_count, 1)
        self.assertEqual(routed.response_path, "gemini_success")
        self.assertEqual(routed.reply.response, answer)
        self.assertIsNotNone(routed.assessment)
        self.assertEqual(routed.assessment.confidence, "high")
        self.assertFalse(routed.assessment.needs_research)

    def test_unvetted_educational_question_still_goes_to_review_if_gemini_fails(
        self,
    ) -> None:
        question = "What does SMT divergence mean in trading?"
        service = GeminiCoachService("test-key")
        router = CoachMessageRouter(service, _EmptyKnowledgeStore())
        with patch(
            "smart_money_hub_bot.gemini_coach.urlopen",
            side_effect=lambda *_args, **_kwargs: _raise_provider_error(
                429, "RESOURCE_EXHAUSTED", "Quota exceeded."
            ),
        ) as mocked_urlopen:
            routed = router.route(989, question)

        self.assertEqual(
            mocked_urlopen.call_count, len(GEMINI_FALLBACK_MODELS) + 1
        )
        self.assertEqual(routed.response_path, "fallback")
        self.assertTrue(routed.reply.requires_review)
        self.assertTrue(routed.assessment.needs_research)
        self.assertIn("flagged", routed.reply.response)

    def test_private_telegram_update_sends_gemini_answer_from_provider(self) -> None:
        synthetic_key = "test-key-never-log"
        synthetic_question = "What is liquidity?"
        generated_answer = "Gemini test answer: liquidity is resting orders around obvious highs and lows."
        api = TelegramAPI("synthetic-test-token")
        with tempfile.TemporaryDirectory() as temp_dir:
            bot = SmartMoneyHubBot(
                api,
                str(Path(temp_dir) / "test.sqlite3"),
                coach_service=GeminiCoachService(synthetic_key),
            )
            update = {
                "update_id": 99,
                "message": {
                    "text": synthetic_question,
                    "chat": {"id": 654321, "type": "private"},
                    "from": {
                        "id": 123456,
                        "username": "synthetic_member",
                        "first_name": "Synthetic",
                    },
                },
            }
            with patch(
                "smart_money_hub_bot.gemini_coach.urlopen",
                return_value=_response(
                    generated_answer,
                    usage_metadata={
                        "promptTokenCount": 90,
                        "candidatesTokenCount": 32,
                        "thoughtsTokenCount": 18,
                        "totalTokenCount": 122,
                    },
                ),
            ) as mocked_urlopen:
                with patch.object(api, "_request") as mocked_telegram_request:
                    with self.assertLogs("smart_money_hub_bot", level="INFO") as logs:
                        bot.handle_update(update)

        self.assertEqual(mocked_urlopen.call_count, 1)
        self.assertEqual(mocked_telegram_request.call_count, 1)
        method, payload = mocked_telegram_request.call_args.args
        self.assertEqual(method, "sendMessage")
        self.assertEqual(payload["chat_id"], 654321)
        self.assertEqual(payload["text"], generated_answer)
        self.assertIn("Coach response path=gemini_success.", "\n".join(logs.output))
        self.assertIn(
            "Coach reply sent to Telegram (path=gemini_success).",
            "\n".join(logs.output),
        )
        log_lines = logs.output
        request_ids = {
            match
            for line in log_lines
            for match in re.findall(r"request_id=([0-9a-f]{32})", line)
        }
        self.assertEqual(len(request_ids), 1)
        request_id = request_ids.pop()
        for expected_log in (
            "Coach request received",
            "Gemini HTTP response",
            "Coach response path=gemini_success",
            "Coach reply sent to Telegram",
        ):
            self.assertTrue(
                any(expected_log in line and request_id in line for line in log_lines),
                expected_log,
            )
        self.assertIn("max_output_tokens=1024", "\n".join(log_lines))
        self.assertIn("'candidate_tokens': 32", "\n".join(log_lines))
        self.assertNotIn(synthetic_question, "\n".join(logs.output))
        self.assertNotIn(synthetic_key, "\n".join(logs.output))
        self.assertNotIn("synthetic_member", "\n".join(logs.output))
        self.assertNotIn("654321", "\n".join(logs.output))

        request = mocked_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(
            payload["contents"][-1]["parts"][0]["text"], synthetic_question
        )
        headers = {key.casefold(): value for key, value in request.header_items()}
        self.assertEqual(headers["x-goog-api-key"], synthetic_key)
        self.assertNotIn(synthetic_key, request.full_url)

    def test_telegram_sends_only_one_reply_after_model_failover(self) -> None:
        synthetic_question = "Explain liquidity in one sentence."
        fallback_answer = "Liquidity is resting orders around watched price levels."
        api = TelegramAPI("synthetic-test-token")
        rate_limit = _provider_error(
            429, "RESOURCE_EXHAUSTED", "Quota temporarily exhausted."
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            bot = SmartMoneyHubBot(
                api,
                str(Path(temp_dir) / "test.sqlite3"),
                coach_service=GeminiCoachService("test-key"),
            )
            update = {
                "update_id": 100,
                "message": {
                    "text": synthetic_question,
                    "chat": {"id": 654321, "type": "private"},
                    "from": {"id": 123456, "first_name": "Synthetic"},
                },
            }
            with patch(
                "smart_money_hub_bot.gemini_coach.urlopen",
                side_effect=[rate_limit, _response(fallback_answer)],
            ) as mocked_urlopen, patch.object(
                api, "_request"
            ) as mocked_telegram_request:
                bot.handle_update(update)

        self.assertEqual(mocked_urlopen.call_count, 2)
        mocked_telegram_request.assert_called_once()
        method, payload = mocked_telegram_request.call_args.args
        self.assertEqual(method, "sendMessage")
        self.assertEqual(payload["text"], fallback_answer)


if __name__ == "__main__":
    unittest.main()
