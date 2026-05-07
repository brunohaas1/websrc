"""Finance security-related routes."""

from __future__ import annotations

import hashlib
import json
import time


def register_security_routes(app, limiter, repo, cache, logger, helpers=None) -> None:
    from flask import jsonify, request

    from ..security import require_finance_key

    @app.get("/api/finance/2fa/status")
    @limiter.limit("30/minute")
    def finance_2fa_status():
        enabled = repo.get_setting("fin_2fa_enabled", "0") == "1"
        return jsonify({"enabled": enabled})

    @app.post("/api/finance/2fa/setup")
    @require_finance_key
    @limiter.limit("10/minute")
    def finance_2fa_setup():
        """Generate a new TOTP secret (does NOT enable 2FA until /enable is called)."""
        try:
            import pyotp  # type: ignore[import-not-found]

            secret = pyotp.random_base32()
            totp = pyotp.TOTP(secret)
            issuer = "WebSRC Finance"
            label = "finance@websrc"
            provisioning_uri = totp.provisioning_uri(name=label, issuer_name=issuer)
            repo.set_setting("fin_2fa_pending_secret", secret)
            return jsonify({"secret": secret, "provisioning_uri": provisioning_uri})
        except Exception as ex:
            return jsonify({"error": str(ex)}), 500

    @app.post("/api/finance/2fa/enable")
    @require_finance_key
    @limiter.limit("10/minute")
    def finance_2fa_enable():
        """Verify TOTP token and activate 2FA."""
        try:
            import pyotp  # type: ignore[import-not-found]

            data = request.get_json(silent=True) or {}
            token = str(data.get("token") or "").strip()
            if not token:
                return jsonify({"error": "token obrigatório"}), 400
            secret = repo.get_setting("fin_2fa_pending_secret", "")
            if not secret:
                return jsonify({"error": "Chame /setup primeiro"}), 400
            totp = pyotp.TOTP(secret)
            if not totp.verify(token, valid_window=1):
                return jsonify({"error": "Código inválido ou expirado"}), 400
            repo.set_setting("fin_2fa_secret", secret)
            repo.set_setting("fin_2fa_enabled", "1")
            repo.set_setting("fin_2fa_pending_secret", "")
            return jsonify({"status": "enabled"})
        except Exception as ex:
            return jsonify({"error": str(ex)}), 500

    @app.post("/api/finance/2fa/verify")
    @limiter.limit("10/minute")
    def finance_2fa_verify():
        """Verify a TOTP token. Returns a short-lived session proof."""
        try:
            import pyotp  # type: ignore[import-not-found]

            data = request.get_json(silent=True) or {}
            token = str(data.get("token") or "").strip()
            if not token:
                return jsonify({"error": "token obrigatório"}), 400
            enabled = repo.get_setting("fin_2fa_enabled", "0") == "1"
            if not enabled:
                return jsonify({"verified": True, "note": "2FA not enabled"})
            secret = repo.get_setting("fin_2fa_secret", "")
            if not secret:
                return jsonify({"error": "2FA não configurado"}), 500
            totp = pyotp.TOTP(secret)
            if not totp.verify(token, valid_window=1):
                return jsonify({"verified": False, "error": "Código inválido"}), 401
            proof = hashlib.sha256(f"{secret}:{totp.now()}:{int(time.time() // 300)}".encode()).hexdigest()[:16]
            return jsonify({"verified": True, "proof": proof})
        except Exception as ex:
            return jsonify({"error": str(ex)}), 500

    @app.post("/api/finance/2fa/disable")
    @require_finance_key
    @limiter.limit("10/minute")
    def finance_2fa_disable():
        """Disable 2FA after verifying current token."""
        try:
            import pyotp  # type: ignore[import-not-found]

            data = request.get_json(silent=True) or {}
            token = str(data.get("token") or "").strip()
            if not token:
                return jsonify({"error": "token obrigatório"}), 400
            secret = repo.get_setting("fin_2fa_secret", "")
            if not secret:
                return jsonify({"error": "2FA não está ativo"}), 400
            totp = pyotp.TOTP(secret)
            if not totp.verify(token, valid_window=1):
                return jsonify({"error": "Código inválido"}), 400
            repo.set_setting("fin_2fa_enabled", "0")
            repo.set_setting("fin_2fa_secret", "")
            repo.set_setting("fin_2fa_pending_secret", "")
            return jsonify({"status": "disabled"})
        except Exception as ex:
            return jsonify({"error": str(ex)}), 500

    @app.post("/api/push/send-test")
    @require_finance_key
    @limiter.limit("5/minute")
    def push_send_test():
        """Send a test push notification to all subscribed browsers."""
        try:
            from pywebpush import WebPushException, webpush  # type: ignore[import-not-found]

            private_key = app.config.get("VAPID_PRIVATE_KEY", "")
            claims_email = app.config.get("VAPID_CLAIMS_EMAIL", "mailto:admin@localhost")
            if not private_key:
                return jsonify({"error": "VAPID_PRIVATE_KEY not configured"}), 400
            subs = repo.list_push_subscriptions()
            if not subs:
                return jsonify({"sent": 0, "note": "no subscribers"})
            payload = json.dumps({
                "title": "🔔 WebSRC Finance",
                "body": "Notificações push estão funcionando!",
                "tag": "test",
                "url": "/finance",
            })
            sent = 0
            failed = 0
            for sub in subs:
                try:
                    keys = json.loads(sub["keys_json"])
                    webpush(
                        subscription_info={"endpoint": sub["endpoint"], "keys": keys},
                        data=payload,
                        vapid_private_key=private_key,
                        vapid_claims={"sub": claims_email},
                    )
                    sent += 1
                except WebPushException as ex:
                    if ex.response and ex.response.status_code == 410:
                        repo.remove_push_subscription(sub["endpoint"])
                    failed += 1
                except Exception:
                    failed += 1
            return jsonify({"sent": sent, "failed": failed})
        except ImportError:
            return jsonify({"error": "pywebpush not installed"}), 500
        except Exception as ex:
            return jsonify({"error": str(ex)}), 500