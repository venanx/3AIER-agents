param appName string

@secure()
param existingSettings object

resource app 'Microsoft.Web/sites@2024-04-01' existing = {
  name: appName
}

resource settings 'Microsoft.Web/sites/config@2024-04-01' = {
  parent: app
  name: 'appsettings'
  properties: union(existingSettings, {
    APP_RELEASE_CHANNEL: 'canary'
  })
}
