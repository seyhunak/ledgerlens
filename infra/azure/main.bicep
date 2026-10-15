// LedgerLens on Azure Container Apps + Key Vault + Log Analytics.
// Deploy: az deployment group create -g <rg> --template-file main.bicep \
//   --parameters image=<registry>/ledgerlens:1.1.0 apiKey=<secret> reviewerKey=<secret>
targetScope = 'resourceGroup'

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Public container image, e.g. myregistry.azurecr.io/ledgerlens:1.1.0')
param image string

@description('Analyst API key (stored in Key Vault, never in code).')
@secure()
param apiKey string

@description('Reviewer API key (stored in Key Vault).')
@secure()
param reviewerKey string

@description('Requests per minute per client before 429.')
param rateLimitPerMin string = '60'

var base = 'ledger${uniqueString(resourceGroup().id)}'

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${base}-logs'
  location: location
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30 }
}

resource kv 'Microsoft.KeyVault/vaults@2024-11-01' = {
  name: '${base}-kv'
  location: location
  properties: {
    sku: { family: 'A', name: 'standard' }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enabledForDeployment: false
    publicNetworkAccess: 'Enabled'
  }
}

resource secretApi 'Microsoft.KeyVault/vaults/secrets@2024-11-01' = {
  parent: kv
  name: 'fin-api-key'
  properties: { value: apiKey }
}

resource secretReviewer 'Microsoft.KeyVault/vaults/secrets@2024-11-01' = {
  parent: kv
  name: 'fin-reviewer-key'
  properties: { value: reviewerKey }
}

resource env 'Microsoft.App/managedEnvironments@2024-10-02-preview' = {
  name: '${base}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

resource app 'Microsoft.App/containerApps@2024-10-02-preview' = {
  name: '${base}-app'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
      }
      secrets: [
        {
          name: 'fin-api-key'
          keyVaultUrl: secretApi.properties.secretUri
          identity: 'system'
        }
        {
          name: 'fin-reviewer-key'
          keyVaultUrl: secretReviewer.properties.secretUri
          identity: 'system'
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'ledgerlens'
          image: image
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: [
            { name: 'FIN_API_KEY', secretRef: 'fin-api-key' }
            { name: 'FIN_REVIEWER_KEY', secretRef: 'fin-reviewer-key' }
            { name: 'RATE_LIMIT_PER_MIN', value: rateLimitPerMin }
          ]
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/health', port: 8000 }
              initialDelaySeconds: 10
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: { path: '/ready', port: 8000 }
              initialDelaySeconds: 5
              periodSeconds: 15
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 5
        rules: [
          { name: 'http', http: { metadata: { concurrentRequests: '20' } } }
        ]
      }
    }
  }
}

// Let the app's managed identity read Key Vault secrets (RBAC).
resource kvRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(kv.id, app.id, 'key-vault-secrets-user')
  scope: kv
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '4633458b-17de-408a-b874-0445c86b69e6' // Key Vault Secrets User
    )
    principalId: app.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

output appUrl string = 'https://${app.properties.configuration.ingress.fqdn}'
output keyVaultName string = kv.name
