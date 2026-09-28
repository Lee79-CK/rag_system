-- 로컬 개발용 샘플 데이터 (docs/README.md §4.2). `make seed`로 실행.
-- Alembic migration(head) 적용 후 실행할 것.

-- 관리자 / 역할
INSERT INTO roles (id, name) VALUES
  ('a0000000-0000-0000-0000-000000000001', 'SYS_ADMIN'),
  ('a0000000-0000-0000-0000-000000000002', 'DOC_ADMIN'),
  ('a0000000-0000-0000-0000-000000000003', 'QUALITY_EVALUATOR'),
  ('a0000000-0000-0000-0000-000000000004', 'AUDITOR')
ON CONFLICT DO NOTHING;

INSERT INTO admin_users (id, login_id, display_name, department, status) VALUES
  ('b0000000-0000-0000-0000-000000000001', 'cklee', '이철규', 'Cloud운영팀', 'ACTIVE'),
  ('b0000000-0000-0000-0000-000000000002', 'docadmin', '문서관리자', '기술기획팀', 'ACTIVE')
ON CONFLICT DO NOTHING;

INSERT INTO user_roles (user_id, role_id) VALUES
  ('b0000000-0000-0000-0000-000000000001', 'a0000000-0000-0000-0000-000000000001'),
  ('b0000000-0000-0000-0000-000000000002', 'a0000000-0000-0000-0000-000000000002')
ON CONFLICT DO NOTHING;

-- Web Chat 채널 / 지식 범위 / Binding
-- chat_channels.id 가 곧 Qdrant allowed_channel_ids 값 (Channel 격리 키).
-- 채팅 사용자/멤버십은 비밀번호 해시가 필요하므로 `make seed-users`(scripts/create_chat_user.py) 로 생성.
INSERT INTO chat_channels (id, name, display_name, type, purpose) VALUES
  ('c0000000-0000-0000-0000-000000000001', 'rag-cloud-ops', 'Cloud 운영 Q&A', 'public',
   'Cloud 운영 매뉴얼·장애대응 문서 질의 (모든 메시지에 응답)'),
  ('c0000000-0000-0000-0000-000000000002', 'rag-hr', '인사 규정 Q&A', 'public',
   '인사 규정 질의 — "!rag 질문" 형식으로 호출')
ON CONFLICT DO NOTHING;

INSERT INTO knowledge_scopes (id, name, filter_json, conversation_mode) VALUES
  ('d0000000-0000-0000-0000-000000000001', 'Cloud 운영 문서',
   '{"categories": ["운영매뉴얼", "장애대응"], "departments": ["Cloud운영팀"], "security_levels": ["INTERNAL"]}', 'THREAD'),
  ('d0000000-0000-0000-0000-000000000002', '인사 규정',
   '{"categories": ["인사규정"], "security_levels": ["INTERNAL"]}', 'CHANNEL')
ON CONFLICT DO NOTHING;

INSERT INTO channel_bindings
  (id, channel_ref, mode, trigger_word, enabled, knowledge_scope_id, history_turns,
   mention_user, ack_message_enabled, feedback_enabled) VALUES
  ('e0000000-0000-0000-0000-000000000001', 'c0000000-0000-0000-0000-000000000001',
   'DEDICATED_CHANNEL', NULL, true, 'd0000000-0000-0000-0000-000000000001', 8,
   false, true, true),
  ('e0000000-0000-0000-0000-000000000002', 'c0000000-0000-0000-0000-000000000002',
   'TRIGGER_WORD', '!rag', true, 'd0000000-0000-0000-0000-000000000002', 8,
   true, true, true)
ON CONFLICT DO NOTHING;

-- 문서 / 버전 / Channel ACL
INSERT INTO documents (id, title, category, department, security_level, status, created_by) VALUES
  ('f0000000-0000-0000-0000-000000000001', '장애대응매뉴얼', '장애대응', 'Cloud운영팀', 'INTERNAL', 'ACTIVE',
   'b0000000-0000-0000-0000-000000000002')
ON CONFLICT DO NOTHING;

INSERT INTO document_versions (id, document_id, version, hash, file_path, file_size, status) VALUES
  ('f1000000-0000-0000-0000-000000000001', 'f0000000-0000-0000-0000-000000000001', 1,
   'sha256:1f2e3d00', '/data/documents/f0000000/1/장애대응매뉴얼.pdf', 2457600, 'ACTIVE')
ON CONFLICT DO NOTHING;

UPDATE documents SET active_version_id = 'f1000000-0000-0000-0000-000000000001'
 WHERE id = 'f0000000-0000-0000-0000-000000000001';

INSERT INTO document_channel_acl (document_id, channel_id, access_type) VALUES
  ('f0000000-0000-0000-0000-000000000001', 'c0000000-0000-0000-0000-000000000001', 'ALLOW')
ON CONFLICT DO NOTHING;

INSERT INTO settings (key, value, updated_by) VALUES
  ('retrieval.vector_top_k', '30', 'b0000000-0000-0000-0000-000000000001'),
  ('retrieval.similarity_threshold', '0.0', 'b0000000-0000-0000-0000-000000000001')
ON CONFLICT DO NOTHING;
