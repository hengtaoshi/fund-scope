"""
基金驾驶舱 — SMTP 邮件发送

发送加仓建议报告到用户邮箱。
SMTP 配置从 config.py 或环境变量读取。
"""
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
from datetime import datetime
from config import SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASS, EMAIL_FROM, FROM_NAME


def _build_html_report(report_data: dict) -> str:
    """生成报告 HTML"""
    holdings = report_data.get("holdings", [])
    portfolio_score = report_data.get("portfolio_score", 0)
    buy_count = report_data.get("buy_recommend", 0)
    today = datetime.now().strftime("%Y年%m月%d日")

    # 构建基金卡片 HTML
    cards_html = ""
    for h in holdings:
        action = h.get("action", "")
        if "买入" in action:
            border_color = "#c62828"
            badge_bg = "#ffebee"
            badge_color = "#c62828"
        elif "减仓" in action or "卖出" in action:
            border_color = "#2e7d32"
            badge_bg = "#e8f5e9"
            badge_color = "#2e7d32"
        else:
            border_color = "#b8860b"
            badge_bg = "#fff7e6"
            badge_color = "#b8860b"

        signals_html = ""
        for s in h.get("signals", []):
            signals_html += f'<span style="display:inline-block;background:{s.get("bg","#f0ebe2")};color:{s.get("color","#8a847a")};padding:2px 8px;border-radius:3px;font-size:11px;margin:2px 4px 2px 0;">{s.get("label","")}</span>'

        cards_html += f"""
        <div style="background:#fff;border-radius:6px;padding:12px;margin-bottom:10px;border-left:3px solid {border_color};">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <div><strong>{h.get('name','')}</strong> <span style="color:#8a847a;font-size:12px;">{h.get('code','')}</span></div>
                <span style="background:{badge_bg};color:{badge_color};padding:2px 10px;border-radius:4px;font-size:12px;font-weight:600;">{action}</span>
            </div>
            <div style="margin-top:8px;display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:12px;">
                <span>综合评分: <strong>{h.get('score','-')}</strong> / 100</span>
                <span>{h.get('level','')}</span>
                <span>年化收益: {h.get('annual_return','-')}%</span>
                <span>最大回撤: {h.get('max_drawdown','-')}%</span>
            </div>
            {f'<div style="margin-top:6px;">{signals_html}</div>' if signals_html else ''}
            {f'<div style="font-size:12px;color:#5a544a;margin-top:6px;padding-top:6px;border-top:1px solid #f0ebe2;">💬 {h.get("comment","")}</div>' if h.get("comment") else ''}
        </div>"""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#faf7f2;padding:20px;">
<div style="max-width:600px;margin:0 auto;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.05);">
    <div style="background:#2c2a26;color:#f5ede0;padding:24px;text-align:center;">
        <h1 style="margin:0;font-size:18px;">📊 基金驾驶舱 · 加仓建议报告</h1>
        <p style="margin:4px 0 0;font-size:12px;color:#b5aea0;">{today}</p>
    </div>
    <div style="padding:20px;">
        <div style="background:#fdf6ec;border:1px solid #f0dcc0;border-radius:8px;padding:16px;margin-bottom:16px;text-align:center;">
            <div style="font-size:13px;color:#8a847a;">组合综合评分</div>
            <div style="font-size:28px;font-weight:700;color:#c7883c;">{portfolio_score} / 100</div>
            <div style="font-size:12px;color:#5a544a;margin-top:4px;">建议加仓 <strong style="color:#c62828;">{buy_count}</strong> 只 · 共 <strong>{len(holdings)}</strong> 只持仓</div>
        </div>
        {cards_html}
        <div style="text-align:center;margin-top:16px;padding-top:16px;border-top:1px solid #e8e0d4;font-size:11px;color:#8a847a;">
            本报告由「基金驾驶舱」自动生成 · 基于多因子评分模型 · 仅供参考，不构成投资建议<br>
            模型: 收益30% + 风控25% + 性价比20% + 技术面15% + 稳定性10%
        </div>
    </div>
</div>
</body>
</html>"""
    return html


def send_report(to_email: str, report_data: dict) -> dict:
    """
    发送加仓报告

    参数:
        to_email: 接收邮箱
        report_data: 报告数据（含 holdings, portfolio_score 等）

    返回:
        dict: { success, message }
    """
    if not SMTP_SERVER or not SMTP_USER or not SMTP_PASS:
        return {"success": False, "message": "SMTP 未配置，请在环境变量中设置 SMTP_SERVER, SMTP_USER, SMTP_PASS"}

    if not to_email:
        return {"success": False, "message": "接收邮箱不能为空"}

    try:
        msg = MIMEMultipart("alternative")
        sender_addr = EMAIL_FROM or SMTP_USER
        msg["From"] = formataddr((FROM_NAME, sender_addr))
        msg["To"] = to_email
        msg["Subject"] = f"基金驾驶舱 · 加仓建议报告 ({datetime.now().strftime('%Y-%m-%d')})"

        html = _build_html_report(report_data)
        msg.attach(MIMEText(html, "html", "utf-8"))

        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        else:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.starttls()

        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(sender_addr, [to_email], msg.as_string())
        server.quit()

        return {"success": True, "message": f"报告已发送至 {to_email}"}

    except smtplib.SMTPAuthenticationError:
        return {"success": False, "message": "SMTP 认证失败，请检查邮箱地址和授权码"}
    except smtplib.SMTPConnectError:
        return {"success": False, "message": f"无法连接到 {SMTP_SERVER}:{SMTP_PORT}"}
    except Exception as e:
        return {"success": False, "message": f"发送失败: {str(e)[:100]}"}


def test_connection() -> dict:
    """测试 SMTP 连接"""
    if not SMTP_SERVER or not SMTP_USER or not SMTP_PASS:
        return {"success": False, "message": "SMTP 未配置"}

    try:
        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=10)
        else:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10)
            server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.quit()
        return {"success": True, "message": f"SMTP 连接成功 ({SMTP_SERVER}:{SMTP_PORT})"}
    except Exception as e:
        return {"success": False, "message": f"连接失败: {str(e)[:100]}"}
