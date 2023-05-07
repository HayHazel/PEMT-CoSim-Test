/*
 * Copyright Xuyang Ma. All Rights Reserved.
 *
 * SPDX-License-Identifier: Apache-2.0
 */

'use strict';

const { Gateway, Wallets } = require('fabric-network');
const path = require('path');
const performance = require('perf_hooks').performance;
const { buildCCPOrg1, buildCCPOrg2, buildWallet, prettyJSONString} = require('../../test-application/javascript/AppUtil.js');
const fs = require('fs');
const {exit} = require('process');

const myChannel = 'mychannel';
const myChaincodeName = 'auction';

async function storeSM(ccp,wallet,user,t,amount) {
	try {

		const gateway = new Gateway();
		await gateway.connect(ccp,
			{ wallet: wallet, identity: user, discovery: { enabled: true, asLocalhost: true } });

		const network = await gateway.getNetwork(myChannel);
		const contract = network.getContract(myChaincodeName);

               let statefulTxn = contract.createTransaction('StoreSM');
		console.log('\n--> store user smart meter');
		let result = await statefulTxn.submit(user,t,amount);
		console.log('*** Result: Committed: ' + result);

		gateway.disconnect();
	} catch (error) {
		console.error(`******** FAILED to store user token: ${error}`);
	}
}

async function main() {
	try {

		if (process.argv[2] === undefined || process.argv[3] === undefined ||
            process.argv[4] === undefined  || process.argv[5] === undefined) {
			console.log('Usage: node storeSM.js org userName time amount ');
			process.exit(1);
		}

		const org = process.argv[2];
		const user = process.argv[3]
		const t = process.argv[4];
		const amount = process.argv[5];
		

		if (org === 'Org1' || org === 'org1') {
			const ccp = buildCCPOrg1();
			const walletPath = path.join(__dirname, 'wallet/org1');
			const wallet = await buildWallet(Wallets, walletPath);
			await storeSM(ccp,wallet,user,t,amount);
		}
		else if (org === 'Org2' || org === 'org2') {
			const ccp = buildCCPOrg2();
			const walletPath = path.join(__dirname, 'wallet/org2');
			const wallet = await buildWallet(Wallets, walletPath);
			await storeSM(ccp,wallet,user,t,amount);
		}  else {
			console.log('Usage: node storeSM.js org name t amount');
			console.log('Org must be Org1 or Org2');
		}
	} catch (error) {
		console.error(`******** FAILED to run the application: ${error}`);
	}
}


main();
