# Canary no Azure (Free F1)

## Arquitetura e estado inicial

| Papel | URL |
|---|---|
| Estável | https://venanx-3aier-agents.azurewebsites.net |
| Canary | https://venanx-3aier-agents-canary.azurewebsites.net |
| Entrada pública | https://venanx-3aier-agents-router.azurewebsites.net |

Três apps Linux Python 3.11 no **mesmo** `plan-3aier-agents`, SKU F1,
RG `rg-3aier-agents`, região `chilecentral`, assinatura
`61933f99-c623-455a-a93d-3fa48eb6b6d0`.
`infra/canary.bicep` referencia o plano existente e só cria os dois novos apps;
não reaplique `infra/main.bicep` para alterar o canary.
Não há slots, upgrade pago, RBAC novo nem alteração de proteção da main.
Pare se houver erro de quota F1; nunca troque de SKU automaticamente.

O router é um redirecionador 302, não proxy. Preserva caminho/query e deixa
WebSockets com o Streamlit. Cookies Secure/HttpOnly/SameSite mantêm o destino
por uma hora **entre 0 e 100**; 0 força estável e 100 força canary, inclusive
com cookie anterior. Configuração inválida falha no startup ou responde 503.
Status em `/_router/status`, sem cache. Percentuais intermediários são
aproximados entre visitantes novos, não proporção exata das requisições.

**Importante:** clientes já redirecionados falam diretamente com o backend.
Mudar o router não migra sessões existentes nem corrige URLs diretas.
Os três apps compartilham quotas de CPU/memória F1, dormem sem tráfego e
não oferecem garantia de disponibilidade. Republicar router pode interrompê-lo.
Não é equivalente operacional aos slots/traffic manager de planos pagos.

## Preparação manual autorizada

Use Azure CLI autenticado na assinatura indicada, com perfil isolado.
Valide antes de provisionar:

```powershell
az appservice plan show -g rg-3aier-agents -n plan-3aier-agents --query sku
az deployment group validate -g rg-3aier-agents --template-file infra\canary.bicep
az deployment group what-if -g rg-3aier-agents --template-file infra\canary.bicep
az deployment group create -g rg-3aier-agents --name canary-infra --template-file infra\canary.bicep
```

Canary: configurar `SCM_DO_BUILD_DURING_DEPLOYMENT=true` e a mesma
`OPENAI_API_KEY` do estável via configuração segura (ARM/portal; não colocar
valor na linha de comando, arquivo versionado, log ou workflow).
Router: `SCM_DO_BUILD_DURING_DEPLOYMENT=false`, startup `python router.py`,
sem chave OpenAI. O Bicep já define startups e HTTPS/TLS.
Configurações são mantidas separadamente da implantação de código.

### Identificação visual

Somente o canary usa `APP_RELEASE_CHANNEL=canary`: faixa e borda vermelhas
com texto explícito **Canary — versão de teste** (texto branco em `#991b1b`,
contraste superior a 4,5:1). O Bicep preserva os demais app settings.
Sem essa variável (ou com outro valor), o layout original permanece intacto,
inclusive quando o mesmo ZIP é promovido para o estável. Não configure a
variável no estável nem no router. Para desenvolvimento local, defina-a no
ambiente do processo; ela não é um segredo.

Para atualizar apenas a identificação no canary existente, sem reaplicar a
infraestrutura ou alterar o router:

```powershell
az webapp config appsettings set -g rg-3aier-agents -n venanx-3aier-agents-canary --settings APP_RELEASE_CHANNEL=canary --output none
```

Depois de **commitar** os arquivos revisados:

```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q
python -m scripts.package_deploy app .canary-build\app.zip
python -m scripts.package_deploy router .canary-build\router.zip --pct 0
az webapp deploy -g rg-3aier-agents -n venanx-3aier-agents-canary --type zip --src-path .canary-build\app.zip
az webapp deploy -g rg-3aier-agents -n venanx-3aier-agents-router --type zip --src-path .canary-build\router.zip
```

O empacotador usa `git archive` de commit resolvido, allowlist de arquivos
necessários e valida o ZIP final. **Nunca use `package: .` ou compacte o
worktree**: `.env`, venv, arquivos locais, perfis e tokens não podem ir ao Azure.
Mudanças não commitadas não são publicadas. `--ref <sha-conhecido>` permite
gerar artefato antigo para restauração. Não crie pacotes com segredos.

## Automação: estratégias mutuamente exclusivas e opt-in

O deploy simples da versão estável está documentado em `DEPLOY_AZURE.md` e
implementado em `.github/workflows/deploy-azure.yml`. Ele pode ser disparado
por push em `main` ou manualmente, mas o job só executa no repositório
`venanx/3AIER-agents`, na branch `main`, com
`DEPLOY_ESTRATEGIA=simple` e após aprovação do environment `production`.
Enquanto a variável estiver ausente (estado atual), os eventos não publicam.

`.github/workflows/deploy-canary.yml` continua apenas `workflow_dispatch`,
restrito ao mesmo repositório, branch e environment, e exige
`DEPLOY_ESTRATEGIA=canary`. As estratégias `simple` e `canary` são
mutuamente exclusivas. Não configure nenhuma das duas antes da revisão externa
e integração aprovada. Configure revisores obrigatórios em `production` antes
de habilitar qualquer estratégia; sem essa regra, o GitHub não solicita
aprovação do environment. Mantenha a proteção da `main`.

Após aprovação, um administrador pode configurar `AZURE_WEBAPP_PUBLISH_PROFILE`
para o app estável (compartilhado pelos workflows simples e canary), além de
`AZURE_CANARY_PUBLISH_PROFILE` e `AZURE_ROUTER_PUBLISH_PROFILE` para o canary.
Perfis são credenciais: somente GitHub Secrets, nunca arquivos, argumentos ou
saída de terminal.
Se a política SCM negar autenticação básica, **não** a altere sem aprovação
do administrador; use deploy manual autenticado via Azure CLI enquanto isso.
Este workflow de publish profiles requer SCM basic auth já autorizado.

Variáveis opcionais: `CANARY_PASSOS` (padrão `10 50`, inteiros crescentes
de 1 a 100) e `CANARY_ESPERA_MIN` (1–15, padrão 5).
A duração total deve caber no timeout de 60 minutos; mantenha rampas curtas.
O grupo de concorrência `deploy-producao` deve ser compartilhado por qualquer
outro fluxo de publicação; não execute deploy manual concorrente.

Fluxo: testes offline → ZIP verificado → estável saudável → deploy canary →
health → rampa/observação → **mesmo ZIP** no estável → health → router 0%.
Health exige `/_stcore/health` com resposta `ok`; não testa resposta do
modelo nem qualidade, custo, taxa de erros de usuário ou estado das sessões.
Nenhuma chamada real OpenAI faz parte destes testes.

## Falha e recuperação

Antes da promoção, falha na rampa tenta router 0%; estável não foi alterado.
Depois que a promoção **começa**, o estável pode estar parcialmente modificado.
O workflow **não restaura** o artefato anterior: verifica canary e tenta
router **100%** para o candidato já testado. O job fica vermelho e exige
intervenção. Isso não é rollback de versão.

Se o canary também falhar, publicação de router falhar, job for cancelado ou
atingir timeout, recuperação automática **não é garantida**. Inspecione
`/_router/status`, os dois health endpoints e o histórico do Azure.
Restaure manualmente um commit estável conhecido:

```powershell
python -m scripts.package_deploy app .canary-build\restore.zip --ref <sha-validado>
az webapp deploy -g rg-3aier-agents -n venanx-3aier-agents --type zip --src-path .canary-build\restore.zip
python -m scripts.canary saude https://venanx-3aier-agents.azurewebsites.net
python -m scripts.package_deploy router .canary-build\router.zip --pct 0
az webapp deploy -g rg-3aier-agents -n venanx-3aier-agents-router --type zip --src-path .canary-build\router.zip
```

Confirme status 0% e redirecionamento para estável; peça aos clientes já
redirecionados para reabrir a URL de entrada. Não declare “estável preservado”
depois de uma tentativa de promoção.

## Evidência da implantação inicial (21/10/2026, sem promoção)

- Infraestrutura `canary-infra`: `Succeeded`; ambos os novos apps no F1 existente.
- ZIPs produzidos pelo empacotador de fonte commitada e allowlist verificada.
- Deploy manual dos apps canary/router: site iniciado com sucesso.
- Router publicado em 0%; status HTTP 200; cookie canary forçado ao estável;
  caminho/query preservados, cookie Secure e redirecionamento sem cache.
- Configurações do canary copiadas do estável via ARM em memória; router sem
  chave OpenAI. Nenhuma política SCM, RBAC ou proteção de branch foi alterada.
- Workflow não habilitado; nenhuma promoção ou chamada de modelo real executada.
- `python -m pytest -q`: **35 passed** (testes offline).
- `python -m scripts.canary saude https://venanx-3aier-agents-canary.azurewebsites.net`:
  passou; o mesmo comando para o estável passou.
- Proteção main consultada: uma aprovação obrigatória e `enforce_admins=true`.
  `DEPLOY_ESTRATEGIA` não configurada.

## Identificação vermelha publicada (21/10/2026, sem promoção)

- Código `f8b264d`, ZIP de allowlist verificada; somente o app canary recebeu
  `APP_RELEASE_CHANNEL=canary` e nova publicação.
- Primeira tentativa expirou no gateway e o build ficou parado; reinício
  somente do canary encerrou a tentativa com falha. Nova publicação assíncrona
  do mesmo ZIP concluiu com status 4, ID `d22b21f5-841d-451f-8d83-fd1812b09a10`.
- Payload real da interface Streamlit verificado via WebSocket: banner Canary
  e fundo `#991b1b` presentes no canary, ausentes no estável. Sem chamada ao modelo.
- Health dos dois apps passou; router permaneceu em 0%. Estável manteve
  deployment `ad177201-5bb9-4dc5-91f0-9497a9157703`, sem flag de canary.
- Testes offline: **41 passed**; validação oficial Bicep/Azure: **OVERALL PASS**.
  Nenhuma reaplicação de infraestrutura, promoção, alteração de SKU ou proteção.
