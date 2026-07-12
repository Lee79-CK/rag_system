import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Button, Input, Popover, Space, Tag, Tooltip, Typography } from 'antd';
import { UserOutlined } from '@ant-design/icons';
import { getAuthUser, setAuthUser } from '../api/client';
import { useWhoami } from '../api/auth';

const { Text } = Typography;

/**
 * Dev-only identity switcher. Sets the `X-Auth-User` header value the client sends
 * (DEC-003 reverse-proxy header trust). In production oauth2-proxy/ingress injects
 * the real header and this control has no effect on the server.
 */
export function AuthUserSwitcher() {
  const qc = useQueryClient();
  const { data: me } = useWhoami();
  const [value, setValue] = useState(getAuthUser());
  const [open, setOpen] = useState(false);

  const apply = () => {
    setAuthUser(value.trim() || 'admin');
    qc.invalidateQueries();
    setOpen(false);
  };

  const content = (
    <div style={{ width: 260 }}>
      <Text type="secondary" style={{ fontSize: 12 }}>
        개발용 <code>X-Auth-User</code> 헤더 값입니다. 운영에서는 IdP/oauth2-proxy가 주입합니다.
      </Text>
      <Space.Compact style={{ width: '100%', marginTop: 8 }}>
        <Input
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onPressEnter={apply}
          placeholder="login id"
        />
        <Button type="primary" onClick={apply}>
          적용
        </Button>
      </Space.Compact>
      {me && (
        <div style={{ marginTop: 10 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            역할:{' '}
          </Text>
          {me.roles.length ? (
            me.roles.map((r) => (
              <Tag key={r} color="blue">
                {r}
              </Tag>
            ))
          ) : (
            <Tag>없음</Tag>
          )}
        </div>
      )}
    </div>
  );

  return (
    <Popover
      content={content}
      title="접속 사용자 (dev)"
      trigger="click"
      open={open}
      onOpenChange={setOpen}
      placement="bottomRight"
    >
      <Tooltip title="개발용 인증 사용자 전환">
        <Button icon={<UserOutlined />}>
          {me?.display_name || me?.login_id || getAuthUser()}
        </Button>
      </Tooltip>
    </Popover>
  );
}
