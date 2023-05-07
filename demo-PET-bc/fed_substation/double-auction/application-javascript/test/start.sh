cd ../../../test-network
./network.sh up createChannel -ca
./network.sh deployCC -ccn auction -ccp ../double-auction/chaincode-go/ -ccl go -ccep "OR('Org1MSP.peer','Org2MSP.peer')"
cd ../double-auction/application-javascript/test
node ../enrollAdmin.js org1
node ../enrollAdmin.js org2
node ../registerEnrollUser.js org1 auctioneer
node ../initMarket.js org1 auctioneer
node ../createAuction.js org1 auctioneer 000
python3 generateBids.py
chmod -R 777 ../wallet
#bash accountReg.sh
#bash bidConfig.sh 000
#for (( i = 1; i <= 1 ; i ++ ))
#do
#  node ../withdraw.js org1 buyer1 000
#done
