# MirrorCore

> Espelhamento de infraestrutura, distribuição de recursos e sincronização de ambientes replicados.

> 🔒 **Software proprietário e confidencial.** Todos os direitos reservados.
> O acesso a este repositório não concede nenhum direito de copiar, distribuir, modificar ou utilizar o código sem autorização prévia e por escrito do autor.

---

## O que o MirrorCore faz

- **Espelhamento de infraestrutura:** replica uma árvore de arquivos de origem em um ou mais destinos.
- **Distribuição:** envia para vários destinos em paralelo (pasta local ou servidor via SSH).
- **Sincronização de ambientes:** detecta divergência (*drift*) e corrige; modo contínuo com `watch`.
- **Replicação de configurações:** arquivos `.tpl` são renderizados com variáveis próprias de cada destino.

A comparação é feita por conteúdo (SHA-256) e as gravações são atômicas.

## Instalação

```bash
pip install -e .
```

Ou sem instalar: `PYTHONPATH=src python -m mirrorcore --help`

## Uso rápido

```bash
mirrorcore init        # cria mirrorcore.json e infra/app.conf.tpl de exemplo
mirrorcore plan        # mostra o que mudaria (não altera nada)
mirrorcore sync        # aplica nos destinos
mirrorcore drift       # sai com código 1 se algum destino divergir
mirrorcore status      # resultado da última sincronização
mirrorcore watch       # sincroniza continuamente (--interval 30)
```

Legenda do plano: `+` criar, `~` atualizar, `-` remover.

## Configuração (`mirrorcore.json`)

| Campo | Descrição |
|-------|-----------|
| `source` | Pasta de origem (relativa ao arquivo de configuração). |
| `targets` | Lista de destinos (veja abaixo). |
| `exclude` | Padrões ignorados (ex.: `*.log`, `.git`). Também protegem arquivos do destino contra remoção. |
| `delete_extraneous` | Se `true`, remove do destino o que não existe na origem. |
| `workers` | Destinos processados em paralelo. |
| `state_dir` | Onde guardar o estado da última sincronização. |
| `interval` | Segundos entre ciclos no `watch`. |
| `template_suffix` | Sufixo dos templates (padrão `.tpl`). |

Destino local:

```json
{ "name": "replica-a", "type": "local", "path": "./replicas/a", "vars": { "ENV": "staging" } }
```

Destino SSH (requer chave configurada; o servidor precisa de `sha256sum`):

```json
{ "name": "srv-sp", "type": "ssh", "host": "10.0.0.10", "user": "deploy", "port": 22,
  "path": "/opt/infra", "vars": { "ENV": "production" } }
```

## Templates

`infra/app.conf.tpl` vira `app.conf` no destino, com `{{VARIAVEL}}` substituída pelos `vars` do destino.
`{{TARGET_NAME}}` está sempre disponível. Variável não definida gera erro.

## Limitações conhecidas

- Divergência de permissões (modo do arquivo) não é detectada; apenas o conteúdo é comparado.
- Os arquivos são lidos inteiros em memória ao enviar.
- Links simbólicos são ignorados.

## Testes

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## Licença

**Todos os direitos reservados.** Veja [LICENSE](./LICENSE).
