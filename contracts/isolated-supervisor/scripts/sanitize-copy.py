"""Remove unreachable upstream cloud credentials from the private build copy.

Do not print input source or produce a diff that includes removed credentials.
The original helper immediately returned true; retain that existing behavior.
"""
from pathlib import Path
import sys
p = Path(sys.argv[1]) / 'supervisor/security.go'
s = p.read_text()
a = s.index('func checkSensitive(')
b = s.index('\nfunc ', a + 5)
s = s[:a] + 'func checkSensitive(str string) bool { return true }\n' + s[b:]
s = '\n'.join(line for line in s.split('\n') if 'tencentcloud' not in line and '"encoding/base64"' not in line)
p.write_text(s)

# The isolated development chain must never ship upstream SMTP credentials.
p = Path(sys.argv[1]) / 'supervisor/claim.go'
s = p.read_text()
a = s.find('//func SendEmail(')
a = s.index('func SendEmail(') if a < 0 else a
b = s.index('func applyclaim(', a)
s = s[:a] + 'func SendEmail(receiver string, code string) error {\n\treturn fmt.Errorf("email delivery is disabled in the isolated Supervisor source")\n}\n' + s[b:]
for name, token in [('crypto/tls', 'tls.'), ('net/smtp', 'smtp.')]:
    if token not in s:
        s = s.replace('\t"' + name + '"\n', '')
p.write_text(s)
