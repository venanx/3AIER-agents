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

## Automação: permanece desligada até revisão externa

`.github/workflows/deploy-canary.yml` é apenas `workflow_dispatch`,
restrito ao repositório `venanx/3AIER-agents`, branch `main`, environment
`production` e variável `DEPLOY_ESTRATEGIA=canary`.
Não configure essa variável antes da revisão externa e integração aprovada.
Configure revisores obrigatórios do environment antes de habilitar; não
reduza proteção da main. Nenhum push automático foi ativado.

Após aprovação, um administrador pode configurar os secrets:
`AZURE_WEBAPP_PUBLISH_PROFILE`, `AZURE_CANARY_PUBLISH_PROFILE`,
`AZURE_ROUTER_PUBLISH_PROFILE`. Perfis são credenciais: somente GitHub
Secrets, nunca arquivos, argumentos ou saída de terminal.
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
