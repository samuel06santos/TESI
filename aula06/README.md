# MCP da AP1: Estilo Marcado

Servidor local em Python/FastMCP para o agente consultar a aplicação Estilo Marcado e criar agendamentos por sua API HTTP. O código e o diário ficam no TESI porque este é o exercício da disciplina; a aplicação permanece no [repositório da AP1](https://github.com/samuel06santos/dsai-ap1-EstiloMarcado).

## Preparar

É necessário Python 3.11+ e `uv`. Na raiz do TESI:

```powershell
uv sync --project aula06
```

Configure a origem da API antes de abrir o agente. Sem a variável, o servidor usa `http://localhost:8080`:

```powershell
$env:ESTILO_MARCADO_API_URL = "http://localhost:8080"
```

As três ferramentas de leitura são públicas. Para criar uma reserva, entre na aplicação com uma conta de cliente e forneça **somente ao processo local** o valor do cookie `SESSION` da mesma origem:

```powershell
$env:ESTILO_MARCADO_SESSION = "valor-da-sessao-atual"
```

Não coloque a sessão no repositório, no prompt nem em `.mcp.json`. Ela expira e o backend verifica o perfil e a filial. O MCP busca o token CSRF na própria API antes da escrita.

## Conectar ao agente

Abra o Claude Code na raiz do TESI com `claude --mcp-config aula06/.mcp.json`. O arquivo [`.mcp.json`](.mcp.json) inicia o servidor via `uv` e [`.claude/settings.json`](../.claude/settings.json) permite as leituras e pede confirmação para `criar_agendamento`. Como o arquivo MCP está nesta subpasta, ele não é descoberto automaticamente ao abrir o TESI; passe o caminho no comando. Veja `/mcp` para conferir a conexão.

Exemplo de tarefa para o agente:

> Encontre uma filial do Estilo Marcado com serviço de corte, consulte os horários disponíveis para amanhã e diga quais opções existem. Não faça reserva.

Para exercitar a escrita com uma conta e uma API de teste, peça explicitamente uma reserva depois de escolher um horário. O cliente solicitará aprovação para a ferramenta de criação.

## Ferramentas

- `listar_filiais`: pesquisa filiais públicas, retornando seus IDs.
- `listar_servicos`: consulta serviços e profissionais da filial.
- `consultar_horarios`: consulta horários válidos de um serviço numa data.
- `criar_agendamento`: reserva um horário para o cliente da sessão. Aceita uma chave UUID opcional para repetir com segurança a mesma tentativa.

O campo `inicio` deve ser a hora local da filial em ISO 8601, como `2026-10-13T14:00:00`, conforme retornado por `consultar_horarios`. Erros da API mantêm o código HTTP e a mensagem pública, sem expor cookies.

## Verificar

```powershell
uv run --project aula06 python -m unittest discover -s aula06/tests -v
```

Os testes simulam a API para conferir rotas, parâmetros, sessão, CSRF e idempotência sem criar reservas reais. Para verificar contra uma API real, inicie o backend da AP1 e use uma sessão de teste.

## Consultar com um agente Ollama

O script [`consultar_com_ollama.py`](consultar_com_ollama.py) conecta um modelo local ao MCP por `stdio`. Ele reaproveita o loop de chamada de ferramentas usado em `aula02/`, mas obtém nomes, descrições e esquemas de parâmetros do servidor MCP. O modelo escolhe as ferramentas; o script executa cada chamada e devolve o resultado à conversa.

Em um terminal, confira que o Ollama está ativo e que há um modelo com suporte a ferramentas (`ollama list`; se necessário, inicie `ollama serve`). Em outro terminal, na raiz do TESI:

```powershell
uv sync --project aula06
uv run --project aula06 python aula06/consultar_com_ollama.py `
  --modelo "qwen3.8:27b-iq4xs" `
  --api-url "https://estilomarcado.samuelsantos.qzz.io" `
  --pergunta "Encontre uma filial com serviço de corte e confirme nome e preço do serviço. Não faça reserva."
```

Troque `--modelo` pelo nome exibido em `ollama list`, se necessário. A execução mostra cada ferramenta escolhida (`MCP: ...`) e, ao final, a resposta do modelo. Este exemplo só oferece `listar_filiais` e `listar_servicos` ao modelo e não passa cookie de sessão ao servidor. O arquivo `aula06/.mcp.json` registra o MCP para Claude Code; o script Ollama cria sua própria conexão com o mesmo servidor.

## Criar um agendamento pelo MCP

Entre na aplicação com uma conta de cliente. No navegador, abra as ferramentas de desenvolvedor, vá a **Aplicativo/Armazenamento → Cookies → domínio da aplicação** e copie o valor do cookie `SESSION`. Ele é uma credencial de acesso: não o envie por chat, não o salve no repositório e não copie o nome `SESSION=`, apenas o valor. O script abaixo pede esse valor de forma oculta no terminal e o passa somente ao processo local do servidor MCP:

```powershell
uv run --project aula06 python aula06/agendar_com_mcp.py --data 2026-10-14
```

O padrão é Unidade Centro (`1000`) e Corte Masculino (`1000`); para outra opção, passe `--unidade-id` e `--servico-id`. O script chama `listar_servicos` e `consultar_horarios`, mostra os horários reais, pede que você escolha um e só chama `criar_agendamento` após digitar `AGENDAR`. Confira os dados antes de confirmar. O resultado mostra o ID da reserva ou o erro retornado pelo MCP.
