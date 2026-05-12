-- =============================================================
-- Seed determinístico do sandbox.
-- Fixtures mínimas para os testes dinâmicos do validator
-- e para a métrica de equivalência comportamental.
-- =============================================================

INSERT INTO clientes (id, nome, cpf, status) VALUES
    (1, 'Cliente Alpha', '11111111111', 'ATIVO'),
    (2, 'Cliente Beta',  '22222222222', 'ATIVO'),
    (3, 'Cliente Gamma', '33333333333', 'INATIVO')
ON CONFLICT (cpf) DO NOTHING;

SELECT setval(pg_get_serial_sequence('clientes', 'id'),
              GREATEST((SELECT MAX(id) FROM clientes), 1));

INSERT INTO contas (id, cliente_id, agencia, numero, tipo, saldo, status) VALUES
    (1, 1, '0001', '100001', 'CORRENTE', 1000.00, 'ATIVA'),
    (2, 1, '0001', '100002', 'POUPANCA',  500.00, 'ATIVA'),
    (3, 2, '0001', '100003', 'CORRENTE',  300.00, 'ATIVA'),
    (4, 2, '0001', '100004', 'SALARIO',   200.00, 'ATIVA'),
    (5, 3, '0001', '100005', 'CORRENTE',    0.00, 'INATIVA')
ON CONFLICT (agencia, numero) DO NOTHING;

SELECT setval(pg_get_serial_sequence('contas', 'id'),
              GREATEST((SELECT MAX(id) FROM contas), 1));

INSERT INTO transacoes (conta_origem_id, conta_destino_id, tipo, valor, data_transacao, status) VALUES
    (NULL, 1, 'DEPOSITO',       1000.00, NOW() - INTERVAL '10 days', 'EFETIVADA'),
    (1,    3, 'TRANSFERENCIA',   200.00, NOW() - INTERVAL '5 days',  'EFETIVADA'),
    (3,    NULL, 'SAQUE',         50.00, NOW() - INTERVAL '2 days',  'EFETIVADA'),
    (NULL, 2, 'DEPOSITO',        500.00, NOW() - INTERVAL '20 days', 'EFETIVADA');

INSERT INTO taxas (tipo_operacao, percentual, valor_minimo, vigente_de) VALUES
    ('TRANSFERENCIA', 0.5000, 2.00, CURRENT_DATE - INTERVAL '1 year'),
    ('SAQUE',         1.0000, 5.00, CURRENT_DATE - INTERVAL '1 year'),
    ('DEPOSITO',      0.1000, 0.50, CURRENT_DATE - INTERVAL '1 year');
