"""Credentials belong to OS secure storage, never settings/project files."""
import keyring
SERVICE='NovelVisualizer.Test.v1'
def get_key(account_id):
    try: return keyring.get_password(SERVICE,account_id) or ''
    except Exception: return ''
def set_key(account_id,value):
    try:
        backend=keyring.get_keyring()
        if 'plaintext' in type(backend).__module__.lower() or 'fail' in type(backend).__module__.lower():
            raise RuntimeError('安全凭据后端不可用')
        if value: keyring.set_password(SERVICE,account_id,value)
        else:
            try: keyring.delete_password(SERVICE,account_id)
            except keyring.errors.PasswordDeleteError: pass
    except Exception as e:
        raise RuntimeError('系统安全凭据存储不可用。未将密钥写入文件；可使用仅本次会话有效的密钥。') from None
