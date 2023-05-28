# fabric-flogging

Clone from flogging of Hyperledger Fabric: 
https://github.com/hyperledger/fabric/tree/master/common/flogging

  (1) `import flogging "github.com/Hnampk/fabric-flogging"`

  (2) Just define `logger   = flogging.MustGetLogger("services.abc.xyz")`

  (3) Then call `logger.Info(...)`, `logger.Warn(...)`, `logger.Error(...)` for logging
