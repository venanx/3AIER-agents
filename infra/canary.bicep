targetScope = 'resourceGroup'

param location string = 'chilecentral'

resource plan 'Microsoft.Web/serverfarms@2024-04-01' existing = {
  name: 'plan-3aier-agents'
}

resource apps 'Microsoft.Web/sites@2024-04-01' = [for role in ['canary', 'router']: {
  name: 'venanx-3aier-agents-${role}'
  location: location
  kind: 'app,linux'
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      appCommandLine: role == 'router' ? 'python router.py' : 'python -m streamlit run app.py --server.port 8000 --server.address 0.0.0.0'
      alwaysOn: false
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
    }
  }
}]

output hostnames array = [for (role, i) in ['canary', 'router']: apps[i].properties.defaultHostName]
