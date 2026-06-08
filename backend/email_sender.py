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


def send_deploy_notification(success: bool, commit_message: str = "", author: str = "", detail: str = "") -> dict:
    """发送部署结果通知"""
    if not SMTP_SERVER or not SMTP_USER or not SMTP_PASS:
        return {"success": False, "message": "SMTP 未配置"}

    to_email = os.getenv("DEPLOY_NOTIFY_EMAIL", "")
    if not to_email:
        return {"success": False, "message": "DEPLOY_NOTIFY_EMAIL 未设置"}

    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status_text = "✅ 部署成功" if success else "❌ 部署失败"
        color = "#2e7d32" if success else "#c62828"

        html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#faf7f2;padding:20px;">
<div style="max-width:560px;margin:0 auto;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.05);">
    <div style="background:#2c2a26;color:#f5ede0;padding:24px;text-align:center;">
        <h1 style="margin:0;font-size:18px;">基金驾驶舱 · 自动部署通知</h1>
    </div>
    <div style="padding:24px;">
        <div style="text-align:center;padding:20px;background:{'#e8f5e9' if success else '#ffebee'};border-radius:8px;margin-bottom:16px;">
            <div style="font-size:36px;margin-bottom:8px;">{'✅' if success else '❌'}</div>
            <div style="font-size:20px;font-weight:600;color:{color};">{status_text}</div>
            <div style="font-size:12px;color:#8a847a;margin-top:4px;">{now}</div>
        </div>
        <table style="width:100%;font-size:13px;border-collapse:collapse;">
            <tr><td style="padding:8px 12px;color:#8a847a;width:80px;">提交信息</td><td style="padding:8px 12px;">{commit_message or '无'}</td></tr>
            <tr style="background:#f8f5f0;"><td style="padding:8px 12px;color:#8a847a;">提交者</td><td style="padding:8px 12px;">{author or '未知'}</td></tr>
            <tr><td style="padding:8px 12px;color:#8a847a;">时间</td><td style="padding:8px 12px;">{now}</td></tr>
            {f'<tr style="background:#f8f5f0;"><td style="padding:8px 12px;color:#8a847a;">详情</td><td style="padding:8px 12px;color:#c62828;">{detail}</td></tr>' if detail else ''}
        </table>
    </div>
    <div style="text-align:center;padding:16px;font-size:11px;color:#8a847a;border-top:1px solid #e8e0d4;">
        基金驾驶舱 · 自动部署系统
    </div>
</div>
</body>
</html>"""

        msg = MIMEMultipart("alternative")
        sender_addr = EMAIL_FROM or SMTP_USER
        msg["From"] = formataddr((FROM_NAME, sender_addr))
        msg["To"] = to_email
        msg["Subject"] = f"基金驾驶舱 · {status_text} ({now[:10]})"
        msg.attach(MIMEText(html, "html", "utf-8"))

        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=15)
        else:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
            server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(sender_addr, [to_email], msg.as_string())
        server.quit()
        return {"success": True, "message": f"通知已发送至 {to_email}"}

    except smtplib.SMTPAuthenticationError:
        return {"success": False, "message": "SMTP 认证失败，请检查邮箱地址和授权码"}
    except smtplib.SMTPConnectError:
        return {"success": False, "message": f"无法连接 SMTP 服务器 {SMTP_SERVER}:{SMTP_PORT}"}
    except Exception as e:
        return {"success": False, "message": f"发送失败: {str(e)[:200]}"}


def send_daily_report(to_email: str, holdings: list, totals: dict) -> dict:
    """
    发送每日收益报告

    参数:
        to_email: 接收邮箱
        holdings: 持仓列表，每项含 name/code/shares/current_nav/yesterday_nav/daily_profit/daily_return_pct/profit/return_pct/current_total
        totals: { total_val, total_daily_profit, total_profit }

    返回:
        dict: { success, message }
    """
    if not SMTP_SERVER or not SMTP_USER or not SMTP_PASS:
        return {"success": False, "message": "SMTP 未配置"}
    if not to_email:
        return {"success": False, "message": "DAILY_REPORT_EMAIL 未设置"}

    today = datetime.now().strftime("%Y年%m月%d日")

    # 构建持仓明细行
    rows_html = ""
    for h in holdings:
        daily = h.get("daily_profit", 0) or 0
        daily_pct = h.get("daily_return_pct", 0) or 0
        total_p = h.get("profit", 0) or 0
        total_pct = h.get("return_pct", 0) or 0
        up = daily >= 0
        color = "#c62828" if up else "#2e7d32"
        arrow = "▲" if up else "▼"
        rows_html += f"""
        <tr>
            <td style="padding:10px 12px;border-bottom:1px solid #f0ebe2;">
                <strong>{h.get('name','')}</strong>
                <div style="font-size:11px;color:#8a847a;">{h.get('code','')} · {h.get('shares',0):.2f}份</div>
            </td>
            <td style="padding:10px 12px;border-bottom:1px solid #f0ebe2;text-align:right;">
                {h.get('current_nav',0):.4f}
            </td>
            <td style="padding:10px 12px;border-bottom:1px solid #f0ebe2;text-align:right;color:{color};">
                {arrow} ¥{abs(daily):.2f}<br>
                <span style="font-size:11px;">{'+' if up else ''}{daily_pct:.2f}%</span>
            </td>
            <td style="padding:10px 12px;border-bottom:1px solid #f0ebe2;text-align:right;">
                ¥{total_p:.2f}<br>
                <span style="font-size:11px;color:{'#c62828' if total_p >= 0 else '#2e7d32'};">{'+' if total_p >= 0 else ''}{total_pct:.2f}%</span>
            </td>
        </tr>"""

    total_daily = totals.get("total_daily_profit", 0) or 0
    total_profit = totals.get("total_profit", 0) or 0
    total_val = totals.get("total_val", 0) or 0
    up_total = total_daily >= 0
    daily_color = "#c62828" if up_total else "#2e7d32"

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#faf7f2;padding:20px;">
<div style="max-width:600px;margin:0 auto;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.05);">
    <div style="background:#2c2a26;color:#f5ede0;padding:24px;text-align:center;">
        <h1 style="margin:0;font-size:18px;">📊 基金驾驶舱 · 每日收益报告</h1>
        <p style="margin:4px 0 0;font-size:12px;color:#b5aea0;">{today}</p>
    </div>
    <div style="padding:20px;">
        <div style="display:flex;gap:12px;margin-bottom:20px;">
            <div style="flex:1;background:#fdf6ec;border-radius:8px;padding:14px;text-align:center;">
                <div style="font-size:12px;color:#8a847a;">总资产</div>
                <div style="font-size:22px;font-weight:700;color:#2d2a26;">¥{total_val:,.2f}</div>
            </div>
            <div style="flex:1;background:{'#fff5f5' if up_total else '#f1f8f4'};border-radius:8px;padding:14px;text-align:center;">
                <div style="font-size:12px;color:#8a847a;">较昨日</div>
                <div style="font-size:22px;font-weight:700;color:{daily_color};">
                    {'+' if up_total else ''}¥{total_daily:,.2f}
                </div>
            </div>
        </div>
        <div style="background:#f8f5f0;border-radius:8px;padding:12px 16px;margin-bottom:16px;text-align:center;">
            <span style="font-size:13px;color:#5a544a;">累计收益 </span>
            <span style="font-size:18px;font-weight:700;color:{'#c62828' if total_profit >= 0 else '#2e7d32'};">{' +' if total_profit >= 0 else ''}¥{total_profit:,.2f}</span>
        </div>
        <table style="width:100%;border-collapse:collapse;font-size:13px;">
            <thead>
                <tr style="background:#f8f5f0;">
                    <th style="padding:10px 12px;text-align:left;color:#8a847a;">基金</th>
                    <th style="padding:10px 12px;text-align:right;color:#8a847a;">净值</th>
                    <th style="padding:10px 12px;text-align:right;color:#8a847a;">较昨日</th>
                    <th style="padding:10px 12px;text-align:right;color:#8a847a;">累计收益</th>
                </tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>
        <div style="text-align:center;margin-top:20px;padding-top:16px;border-top:1px solid #e8e0d4;font-size:11px;color:#8a847a;">
            本报告由「基金驾驶舱」每日自动生成 · 仅供参考，不构成投资建议
        </div>
    </div>
</div>
</body>
</html>"""

    try:
        msg = MIMEMultipart("alternative")
        sender_addr = EMAIL_FROM or SMTP_USER
        msg["From"] = formataddr((FROM_NAME, sender_addr))
        msg["To"] = to_email
        msg["Subject"] = f"基金驾驶舱 · 每日收益报告 ({datetime.now().strftime('%Y-%m-%d')})"

        msg.attach(MIMEText(html, "html", "utf-8"))

        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=15)
        else:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=15)
            server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(sender_addr, [to_email], msg.as_string())
        server.quit()

        return {"success": True, "message": f"每日报告已发送至 {to_email}"}

    except smtplib.SMTPAuthenticationError:
        return {"success": False, "message": "SMTP 认证失败，请检查邮箱地址和授权码"}
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
