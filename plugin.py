"""群关系观察：本群互动网络、报告与管理员看板。"""
from __future__ import annotations

from pydantic import Field

from nekro_agent.api.plugin import (
    Arg, CmdCtl, CommandExecutionContext, CommandPermission, ConfigBase,
    ExtraField, NekroPlugin, SandboxMethodType,
)
from nekro_agent.api.schemas import AgentCtx
from nekro_agent.api.message import ChatMessage

from .render import text_report
from .service import RelationsService, extract

plugin = NekroPlugin(
    name="群关系观察", module_name="group_relations", author="JiaDodo", version="0.1.0",
    description="基于本群 @ 与引用回复生成互动关系图、聊天搭子排行和娱乐报告，附管理员 Web 看板。",
    url="https://github.com/JiaDodo/nekro-plugin-group-relations", support_adapter=["onebot_v11"],
    allow_sleep=True, sleep_brief="分析本群互动关系、查询我的聊天搭子、生成群关系图和关系周报。",
)


@plugin.mount_config()
class RelationsConfig(ConfigBase):
    GROUP_ALLOWLIST: list[str] = Field(default_factory=list, title="群白名单", description="填完整 chat_key，如 onebot_v11-group_123456。留空允许所有 QQ 群。")
    RETENTION_DAYS: int = Field(default=90, ge=60, le=365, title="互动记录保留天数")
    MAX_HISTORY_MESSAGES: int = Field(default=50000, ge=1000, le=200000, title="单次历史同步消息上限", description="超过上限会明确显示样本不完整。")
    MIN_EDGE_EVENTS: int = Field(default=2, ge=1, le=20, title="关系图最少互动次数")
    DAILY_PAIR_CAP: int = Field(default=20, ge=1, le=200, title="单日单向互动计分上限", description="实际次数完整展示，仅限制刷屏对互动指数的影响。")
    ENABLE_AI_COMMENT: bool = Field(default=False, title="启用 AI 娱乐点评", description="手动请求时才调用模型，仅发送统计与昵称，不发送聊天正文。")
    MODEL_GROUP: str = Field(default="", title="点评模型组", description="留空使用系统主模型组。", json_schema_extra=ExtraField(ref_model_groups=True, model_type="chat").model_dump())
    RENDER_ENDPOINT: str = Field(default="http://nekro_html2img:3000", title="图片渲染服务", description="browserless Chromium 服务；必须由管理员配置。")
    RENDER_TOKEN: str = Field(default="", title="图片渲染令牌", json_schema_extra=ExtraField(is_secret=True).model_dump())
    RENDER_TIMEOUT: int = Field(default=60, ge=10, le=180, title="渲染超时秒数")


_service: RelationsService | None = None


def config() -> RelationsConfig:
    return plugin.get_config(RelationsConfig)


def service() -> RelationsService:
    if _service is None:
        raise RuntimeError("关系插件尚未完成初始化")
    return _service


@plugin.mount_init_method()
async def initialize():
    global _service
    _service = RelationsService(plugin, config)
    await _service.start()
    plugin.logger.info("群关系观察已就绪；看板 /plugins/JiaDodo.group_relations/")


@plugin.mount_cleanup_method()
async def cleanup():
    global _service
    if _service:
        await _service.stop()
        _service = None


@plugin.mount_on_user_message()
async def collect(_ctx: AgentCtx, message: ChatMessage):
    if not _service or not _service.allowed(message.chat_key):
        return None
    try:
        row = extract(message, _service.bot_ids.get(message.chat_key, ""))
        if row["sender"] != _service.bot_ids.get(message.chat_key):
            _service.enqueue(message.chat_key, _ctx.channel_name or message.chat_key, row)
    except Exception:
        plugin.logger.warning("忽略无法解析的互动消息；正常聊天继续处理")
    return None


async def deliver(ctx: AgentCtx, days: int, image: bool = True, ai: bool = False):
    report = await service().report(ctx.chat_key, days, ai=ai)
    if image:
        try:
            path = await service().image(report)
            await ctx.send_image(str(path))
            return "群关系报告图片已发送。" + (" " + report["warning"] if report["warning"] else "")
        except Exception:
            plugin.logger.warning("群关系图片生成或发送失败，回退文字报告")
    return text_report(report)


@plugin.mount_command(name="relations", aliases=["群关系图", "群关系周报"], description="生成本群关系图片报告", permission=CommandPermission.PUBLIC, usage="relations [days]", category="群关系")
async def relations_command(context: CommandExecutionContext, days: int = Arg("最近天数，1–30", default=7, positional=True)):
    try:
        ctx = await AgentCtx.create_by_chat_key(context.chat_key)
        return CmdCtl.success(await deliver(ctx, days))
    except ValueError as e:
        return CmdCtl.failed(str(e))
    except Exception:
        plugin.logger.exception("关系报告生成失败")
        return CmdCtl.failed("关系报告暂时不可用，请查看插件日志。")


@plugin.mount_command(name="my_relations", aliases=["我的群关系"], description="查看自己在本群的互动搭子", permission=CommandPermission.PUBLIC, usage="my_relations [days]", category="群关系")
async def my_command(context: CommandExecutionContext, days: int = Arg("最近天数，1–30", default=7, positional=True)):
    try:
        return CmdCtl.success(text_report(await service().report(context.chat_key, days), str(context.user_id)))
    except ValueError as e:
        return CmdCtl.failed(str(e))


@plugin.mount_command(name="relations_optout", aliases=["退出关系统计"], description="退出本群关系统计并清理自己的互动数据", permission=CommandPermission.PUBLIC, category="群关系")
async def optout_command(context: CommandExecutionContext):
    import asyncio
    await service().channel(context.chat_key)
    await asyncio.to_thread(service().repo.opt_out, context.chat_key, str(context.user_id), True)
    await asyncio.to_thread(service().purge_exports)
    service().invalidate(context.chat_key)
    return CmdCtl.success("你已退出本群关系统计，插件中的个人互动记录已清理。")


@plugin.mount_command(name="relations_optin", aliases=["加入关系统计"], description="重新加入本群关系统计", permission=CommandPermission.PUBLIC, category="群关系")
async def optin_command(context: CommandExecutionContext):
    import asyncio
    await service().channel(context.chat_key)
    await asyncio.to_thread(service().repo.opt_out, context.chat_key, str(context.user_id), False)
    service().invalidate(context.chat_key)
    return CmdCtl.success("你已重新加入；之后的历史同步可能重新导入仍保留的群聊互动。")


@plugin.mount_sandbox_method(SandboxMethodType.TOOL, name="分析本群关系", description="分析当前群的互动关系，可生成图片；仅访问当前群。")
async def analyze_group_relations(_ctx: AgentCtx, days: int = 7, send_image: bool = True, ai_comment: bool = False) -> str:
    """Analyze this group using explicit @ and quoted replies. days: 1–30. send_image sends a PNG report.
    ai_comment optionally requests configured AI commentary. Never infer real romantic relationships or hostility.
    """
    return await deliver(_ctx, days, send_image, ai_comment)


@plugin.mount_sandbox_method(SandboxMethodType.TOOL, name="查询我的群关系", description="查询触发者在当前群的互动搭子。")
async def get_my_group_relations(_ctx: AgentCtx, days: int = 7) -> str:
    """Show the triggering user's interaction partners in the current group. days: 1–30."""
    user = _ctx.db_user
    if not user:
        return "无法确认本次请求的用户，请使用 /my_relations 命令。"
    return text_report(await service().report(_ctx.chat_key, days), str(user.platform_userid))


@plugin.mount_router()
def mount_web():
    from .web import create_router
    return create_router(service)
