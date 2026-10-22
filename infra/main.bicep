targetScope = 'subscription'

param location string = 'chilecentral'

resource group 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-3aier-agents'
  location: location
}

module app './webapp.bicep' = {
  name: 'agent-webapp'
  scope: group
  params: {
    location: location
  }
}

output hostname string = app.outputs.hostname
