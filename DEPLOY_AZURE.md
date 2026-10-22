# Deploy simples no Azure

Este fluxo publica a versão estável do `venanx/3AIER-agents` no Azure App
Service `venanx-3aier-agents`. O recurso existente roda Linux/Python 3.11 no
plano gratuito F1 em Chile Central. O deploy inicial foi feito manualmente
pela Azure CLI; o workflow abaixo é uma opção futura para automatizar novas
publicações.

> **Estado atual:** o app está parado por solicitação do usuário. Não configure
> o workflow nem faça push de ativação sem autorização para voltar a publicar e
> iniciar o serviço. Um deploy pode tirar o app do estado parado.

## Proteções do workflow

`.github/workflows/deploy-azure.yml`:

- Só roda no repositório `venanx/3AIER-agents` e na branch `main`.
- Dispara em push para `main` **ou** manualmente pela aba Actions. Pull
  requests e branches de trabalho não publicam.
- O job só executa quando a variável do repositório
  `DEPLOY_ESTRATEGIA` está exatamente como `simple`. Sem ela, o job é pulado.
- Usa o environment `production`. Configure nele um revisor obrigatório em
  **Settings → Environments → production → Required reviewers** antes de
  habilitar o fluxo. Sem essa regra, a aprovação não é aplicada pelo GitHub.
- Executa testes offline e cria o pacote de deploy com `git archive` e uma
  allowlist de arquivos rastreados; não compacta o worktree nem inclui `.env`,
  tokens, perfis ou arquivos locais.
- Valida que o publish profile corresponde exatamente ao App Service estável
  antes de enviá-lo ao Azure; publica somente o app estável e verifica o health
  endpoint.
- Usa o mesmo grupo de concorrência `deploy-producao` do workflow canary para
  impedir publicações simultâneas.

## Preparação (apenas depois da revisão e autorização)

1. Revise e integre o PR na `main`, mantendo a proteção de branch e o CODEOWNER.
2. Em **Settings → Environments**, crie `production` e configure os revisores
   obrigatórios. Não prossiga se a aprovação não estiver configurada.
3. Em **Settings → Secrets and variables → Actions → Variables**, defina
   `DEPLOY_ESTRATEGIA` como `simple`. **A partir daí, cada push na `main` pode
   iniciar um deploy**, sujeito à aprovação do environment. O workflow canary
   não roda enquanto essa variável não for `canary`.
4. Em **Settings → Secrets and variables → Actions → Secrets**, crie
   `AZURE_WEBAPP_PUBLISH_PROFILE` com o conteúdo do publish profile do recurso
   `venanx-3aier-agents`. Trate-o como uma credencial: não o salve no Git, em
   arquivos locais compartilhados, logs ou mensagens.
5. Antes de cada publicação, confira o diff, os testes, o estado operacional
   do Azure e a aprovação do environment. Para iniciar manualmente, abra
   **Actions → Deploy Azure → Run workflow**, selecionando a branch `main`.
   Pushes na `main` também acionam o fluxo quando a estratégia está habilitada.

## Configuração do App Service

O publish profile publica código; ele não configura a chave do modelo. No
App Service estável, mantenha `OPENAI_API_KEY` em **Settings → Environment
variables → App settings** e `SCM_DO_BUILD_DURING_DEPLOYMENT=true`. Nunca
coloque a chave no repositório ou em um secret de deploy do GitHub. O comando
de inicialização esperado é:

```text
python -m streamlit run app.py --server.port 8000 --server.address 0.0.0.0
```

O Bicep `infra/webapp.bicep` define o runtime e o comando de inicialização para
a infraestrutura criada por este projeto. O deploy não recria a infraestrutura
nem altera o plano, as configurações de app, o tráfego canary ou a proteção da
branch.

## Desativar

Para interromper novos deploys automáticos, remova a variável
`DEPLOY_ESTRATEGIA` ou altere-a para um valor diferente de `simple`. Remover
somente o secret fará o job falhar na validação se continuar habilitado. Isso
não para nem remove o App Service.

## Uso em forks

O workflow é deliberadamente restrito ao repositório e ao hostname estável de
`venanx/3AIER-agents`. Um fork deve revisar e ajustar a condição do repositório,
hostname validado e nome do App Service antes de configurar secrets; não copie
o publish profile deste projeto.
