import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from discord.ext.commands import errors

from bot.api import ResponseCodeError
from bot.cogs.error_handler import ErrorHandler
from bot.cogs.moderation.silence import Silence
from tests.helpers import MockBot, MockContext


class ErrorHandlerTests(unittest.IsolatedAsyncioTestCase):
    """Tests for error handler functionality."""

    def setUp(self):
        self.bot = MockBot()
        self.ctx = MockContext(bot=self.bot)

    async def test_error_handler_already_handled(self):
        """Should not do anything when error is already handled by local error handler."""
        self.ctx.reset_mock()
        cog = ErrorHandler(self.bot)
        error = errors.CommandError()
        error.handled = "foo"
        self.assertIsNone(await cog.on_command_error(self.ctx, error))
        self.ctx.send.assert_not_awaited()

    async def test_error_handler_command_not_found_error_not_invoked_by_handler(self):
        """Should try first (un)silence channel, when fail and channel is not verification channel try to get tag."""
        error = errors.CommandNotFound()
        test_cases = (
            {
                "try_silence_return": True,
                "patch_verification_id": False,
                "called_try_get_tag": False
            },
            {
                "try_silence_return": False,
                "patch_verification_id": True,
                "called_try_get_tag": False
            },
            {
                "try_silence_return": False,
                "patch_verification_id": False,
                "called_try_get_tag": True
            }
        )
        cog = ErrorHandler(self.bot)
        cog.try_silence = AsyncMock()
        cog.try_get_tag = AsyncMock()

        for case in test_cases:
            with self.subTest(try_silence_return=case["try_silence_return"], try_get_tag=case["called_try_get_tag"]):
                self.ctx.reset_mock()
                cog.try_silence.reset_mock(return_value=True)
                cog.try_get_tag.reset_mock()

                cog.try_silence.return_value = case["try_silence_return"]
                self.ctx.channel.id = 1234

                if case["patch_verification_id"]:
                    with patch("bot.cogs.error_handler.Channels.verification", new=1234):
                        self.assertIsNone(await cog.on_command_error(self.ctx, error))
                else:
                    self.assertIsNone(await cog.on_command_error(self.ctx, error))
                if case["try_silence_return"]:
                    cog.try_get_tag.assert_not_awaited()
                    cog.try_silence.assert_awaited_once()
                else:
                    cog.try_silence.assert_awaited_once()
                    if case["patch_verification_id"]:
                        cog.try_get_tag.assert_not_awaited()
                    else:
                        cog.try_get_tag.assert_awaited_once()
                self.ctx.send.assert_not_awaited()

    async def test_error_handler_command_not_found_error_invoked_by_handler(self):
        """Should do nothing when error is `CommandNotFound` and have attribute `invoked_from_error_handler`."""
        ctx = MockContext(bot=self.bot, invoked_from_error_handler=True)

        cog = ErrorHandler(self.bot)
        cog.try_silence = AsyncMock()
        cog.try_get_tag = AsyncMock()

        error = errors.CommandNotFound()

        self.assertIsNone(await cog.on_command_error(ctx, error))

        cog.try_silence.assert_not_awaited()
        cog.try_get_tag.assert_not_awaited()
        self.ctx.send.assert_not_awaited()

    async def test_error_handler_user_input_error(self):
        """Should await `ErrorHandler.handle_user_input_error` when error is `UserInputError`."""
        self.ctx.reset_mock()
        cog = ErrorHandler(self.bot)
        cog.handle_user_input_error = AsyncMock()
        error = errors.UserInputError()
        self.assertIsNone(await cog.on_command_error(self.ctx, error))
        cog.handle_user_input_error.assert_awaited_once_with(self.ctx, error)

    async def test_error_handler_check_failure(self):
        """Should await `ErrorHandler.handle_check_failure` when error is `CheckFailure`."""
        self.ctx.reset_mock()
        cog = ErrorHandler(self.bot)
        cog.handle_check_failure = AsyncMock()
        error = errors.CheckFailure()
        self.assertIsNone(await cog.on_command_error(self.ctx, error))
        cog.handle_check_failure.assert_awaited_once_with(self.ctx, error)

    async def test_error_handler_command_on_cooldown(self):
        """Should send error with `ctx.send` when error is `CommandOnCooldown`."""
        self.ctx.reset_mock()
        cog = ErrorHandler(self.bot)
        error = errors.CommandOnCooldown(10, 9)
        self.assertIsNone(await cog.on_command_error(self.ctx, error))
        self.ctx.send.assert_awaited_once_with(error)

    async def test_error_handler_command_invoke_error(self):
        """Should call `handle_api_error` or `handle_unexpected_error` depending on original error."""
        cog = ErrorHandler(self.bot)
        cog.handle_api_error = AsyncMock()
        cog.handle_unexpected_error = AsyncMock()
        test_cases = (
            {
                "args": (self.ctx, errors.CommandInvokeError(ResponseCodeError(AsyncMock()))),
                "expect_mock_call": cog.handle_api_error
            },
            {
                "args": (self.ctx, errors.CommandInvokeError(TypeError)),
                "expect_mock_call": cog.handle_unexpected_error
            }
        )

        for case in test_cases:
            with self.subTest(args=case["args"], expect_mock_call=case["expect_mock_call"]):
                self.assertIsNone(await cog.on_command_error(*case["args"]))
                case["expect_mock_call"].assert_awaited_once_with(self.ctx, case["args"][1].original)

    async def test_error_handler_three_other_errors(self):
        """Should call `handle_unexpected_error` when `ConversionError`, `MaxConcurrencyReached` or `ExtensionError`."""
        cog = ErrorHandler(self.bot)
        cog.handle_unexpected_error = AsyncMock()
        errs = (
            errors.ConversionError(MagicMock(), MagicMock()),
            errors.MaxConcurrencyReached(1, MagicMock()),
            errors.ExtensionError(name="foo")
        )

        for err in errs:
            with self.subTest(error=err):
                cog.handle_unexpected_error.reset_mock()
                self.assertIsNone(await cog.on_command_error(self.ctx, err))
                cog.handle_unexpected_error.assert_awaited_once_with(self.ctx, err)

    @patch("bot.cogs.error_handler.log")
    async def test_error_handler_other_errors(self, log_mock):
        """Should `log.debug` other errors."""
        cog = ErrorHandler(self.bot)
        error = errors.DisabledCommand()  # Use this just as a other error
        self.assertIsNone(await cog.on_command_error(self.ctx, error))
        log_mock.debug.assert_called_once()


class TrySilenceTests(unittest.IsolatedAsyncioTestCase):
    """Test for helper functions that handle `CommandNotFound` error."""

    def setUp(self):
        self.bot = MockBot()

    async def test_try_silence_context_invoked_from_error_handler(self):
        """Should set `Context.invoked_from_error_handler` to `True`."""
        cog = ErrorHandler(self.bot)
        ctx = MockContext(bot=self.bot)
        ctx.invoked_with = "foo"
        self.bot.get_command.return_value = Silence(self.bot).silence
        await cog.try_silence(ctx)
        self.assertTrue(hasattr(ctx, "invoked_from_error_handler"))
        self.assertTrue(ctx.invoked_from_error_handler)

    async def test_try_silence_get_command(self):
        """Should call `get_command` with `silence`."""
        cog = ErrorHandler(self.bot)
        ctx = MockContext(bot=self.bot)
        ctx.invoked_with = "foo"
        self.bot.get_command.return_value = Silence(self.bot).silence
        await cog.try_silence(ctx)
        self.bot.get_command.assert_called_once_with("silence")
