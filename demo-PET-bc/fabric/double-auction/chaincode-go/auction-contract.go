/*
 * SPDX-License-Identifier: Apache-2.0
 */

package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"strconv"

	flogging "github.com/Hnampk/fabric-flogging"
	"github.com/hyperledger/fabric-contract-api-go/contractapi"
)

type BidRes struct {
	Units  int     `json:"units"`
	Prices float64 `json:"prices"`
}

type AuctionContract struct {
	contractapi.Contract
}

func (c *AuctionContract) AuctionExists(ctx contractapi.TransactionContextInterface, auctionID string) (bool, error) {
	data, err := ctx.GetStub().GetState(auctionID)
	if err != nil {
		return false, err
	}
	return data != nil, nil
}

func (c *AuctionContract) InitFeedbackSystem(ctx contractapi.TransactionContextInterface, addr string) error {
	if addr != "auctioneer" {
		return fmt.Errorf("illegal user %s tries to build feedback system", addr)
	}
	accounts := new(Accounts)
	bytes, _ := json.Marshal(accounts)
	return ctx.GetStub().PutState("acc", bytes)
}

func (c *AuctionContract) RegisterAccount(ctx contractapi.TransactionContextInterface, addr string, balance float64) error {
	bytes, _ := ctx.GetStub().GetState("acc")
	accounts := new(Accounts)
	err := json.Unmarshal(bytes, accounts)
	if err != nil {
		return fmt.Errorf("could not unmarshal world state data to type Auction")
	}
	// The element to search for
	element := Hash(addr)
	// Iterate over the elements of the list, it can be finished in a simpler way
	for _, e := range accounts.Address {
		if e == element {
			return fmt.Errorf("we have already registered this account. %s", addr)
		}
	}
	accounts.Address = append(accounts.Address, Hash(addr))
	accounts.Balance = append(accounts.Balance, balance)
	bytes, _ = json.Marshal(accounts)
	ctx.GetStub().PutState("acc", bytes)

	//create shared smart meter address
	addr_new := addr + "1"
	address_sm := Hash(addr_new)
	sm := new(SMarray)
	bytes, _ = json.Marshal(sm)
	ctx.GetStub().PutState(address_sm, bytes)

	//create wallet
	accounts1 := Accounts1{
		Name:    addr,
		Address: element,
		Balance: balance,
	}
	bytes, _ = json.Marshal(accounts1)
	return ctx.GetStub().PutState(element, bytes)
}

//create shared wallet2  without bidding result
func (c *AuctionContract) CreateSharedWallet(ctx contractapi.TransactionContextInterface, Name string) error {

	addressSW := Hash(Name)
	sharedWallet := SharedWallet{
		Seller_Balance: 0,
		Buyer_Balance:  0,
	}
	bytes, _ := json.Marshal(sharedWallet)
	return ctx.GetStub().PutState(addressSW, bytes)
}

// Dependant functions include Transfer and TransferFrom without bidding result
func (c *AuctionContract) transferHelper(ctx contractapi.TransactionContextInterface, from string, to string, value float64, flag int) error {

	if from == to {
		return fmt.Errorf("cannot transfer to and from same client account")
	}

	if value < 0 { //   validate against negative amounts
		return fmt.Errorf("transfer amount cannot be negative")
	}

	//init sharedwallet
	if (flag == 1) || flag == 2 {
		//get sender assets sender is user
		senderAsset, err := c.ReadAccounts2(ctx, from)
		if err != nil {
			return fmt.Errorf("failed to get account %v", err)
		}

		//get reveive assets  reveive is sharedwallet
		receiveAsset, err := c.ReadSharedWallet(ctx, to)
		if err != nil {
			return fmt.Errorf("failed to read receive asset %s from world state: %v", to, err)
		}

		//store tokens
		senderAsset.Balance -= value

		if flag == 1 {
			receiveAsset.Seller_Balance += value
		} else if flag == 2 {
			receiveAsset.Buyer_Balance += value
		}
		//update
		assetJSON, err := json.Marshal(senderAsset)
		if err != nil {
			return err
		}
		err = ctx.GetStub().PutState(from, assetJSON)
		if err != nil {
			return nil
		}

		assetJSON2, err := json.Marshal(receiveAsset)
		if err != nil {
			return err
		}
		err = ctx.GetStub().PutState(to, assetJSON2)
		if err != nil {
			return nil
		}
	} else {
		//refund sender is sharedwallet.receive is user
		senderAsset, err := c.ReadSharedWallet(ctx, from)
		if err != nil {
			return fmt.Errorf("failed to get account %v", err)
		}

		receiveAsset, err := c.ReadAccounts2(ctx, to)
		if err != nil {
			return fmt.Errorf("failed to read receive asset %s from world state: %v", to, err)
		}

		//transaction

		if flag == 3 {
			senderAsset.Seller_Balance -= value
		} else if flag == 4 {
			senderAsset.Buyer_Balance -= value
		}
		receiveAsset.Balance += value
		//update
		assetJSON, err := json.Marshal(senderAsset)
		if err != nil {
			return err
		}
		err = ctx.GetStub().PutState(from, assetJSON)
		if err != nil {
			return nil
		}

		assetJSON2, err := json.Marshal(receiveAsset)
		if err != nil {
			return err
		}
		err = ctx.GetStub().PutState(to, assetJSON2)
		if err != nil {
			return nil
		}
	}
	return nil

}

func (c *AuctionContract) initShareWallet(ctx contractapi.TransactionContextInterface, swName string, userName string, amount float64, flag int) error {

	//transfer 1 means seller,2 means buyer
	if flag == 1 {
		err := c.transferHelper(ctx, userName, swName, amount, 1)
		if err != nil {
			return fmt.Errorf("failed to transfer %v", err)
		}

	} else {
		err := c.transferHelper(ctx, userName, swName, amount, 2)
		if err != nil {
			return fmt.Errorf("failed to transfer %v", err)
		}
	}
	return nil
}

//after bidding ,store users tokens
func (c *AuctionContract) StoreToken(ctx contractapi.TransactionContextInterface, auctionID string, name string) (string, error) {
	var res string
	exists, err := c.AuctionExists(ctx, auctionID)
	if err != nil {
		return res, fmt.Errorf("could not read from world state. %s", err)
	} else if !exists {
		return res, fmt.Errorf("no %s auction", auctionID)
	}

	bytes, _ := ctx.GetStub().GetState(auctionID)
	auction := new(Auction)
	json.Unmarshal(bytes, auction)
	if !auction.Closed {
		// winners := Allocate(auction.Buyers, auction.Sellers)
		buyersPay, sellersPay, clearedUnits, clearedPrice := DeterminePayment(auction.Buyers, auction.Sellers)
		bytes, _ = ctx.GetStub().GetState("acc")
		accounts := new(Accounts)
		err = json.Unmarshal(bytes, accounts)
		if err != nil {
			return res, fmt.Errorf("could not unmarshal world state data to type Auction")
		}

		//store buyer
		for i := 0; i < len(auction.Buyers); i++ {
			baddr := auction.Buyers[i].Address
			auction.BuyersPay[i] = buyersPay[i]
			c.initShareWallet(ctx, name, baddr, auction.BuyersPay[i], 2)

		}
		//store seller
		for i := 0; i < len(auction.Sellers); i++ {
			saddr := auction.Sellers[i].Address
			auction.SellersPay[i] = sellersPay[i]
			c.initShareWallet(ctx, name, saddr, 2, 1)

		}
		bytes, _ = json.Marshal(accounts)
		ctx.GetStub().PutState("acc", bytes)

		bytes, _ = json.Marshal(auction)
		ctx.GetStub().PutState("000", bytes)

		bidRes := &BidRes{
			Units:  clearedUnits,
			Prices: clearedPrice,
		}
		// Encode the data as a pretty-printed JSON string
		data, err := json.MarshalIndent(bidRes, "", "    ")
		if err != nil {
			panic(err)
		}
		return string(data), err
	}

	return res, err
}

//refund function without bidding result
func (c *AuctionContract) Refund(ctx contractapi.TransactionContextInterface, userName string, swName string, amount float64, flag int) error {

	//judge transfer
	switch {
	//flag ==3 means buyer's tokens to seller,flag == 4 means that seller gets own tokens flag ==5 means seller is malicous,tokens to buyer
	case flag == 3:
		err := c.transferHelper(ctx, swName, userName, amount, 3)
		if err != nil {
			return fmt.Errorf("seller is malicious,failed to transfer %v", err)
		}

	case flag == 4:
		err := c.transferHelper(ctx, swName, userName, amount, 4)
		if err != nil {
			return fmt.Errorf("buyer is malicious,failed to transfer %v", err)
		}

	case flag == 5:
		err := c.transferHelper(ctx, swName, userName, amount, 5)
		if err != nil {
			return fmt.Errorf("ERROR %v", err)
		}
		//Return to respective accounts
	default:
		err := c.transferHelper(ctx, swName, userName, amount, 5)
		if err != nil {
			return fmt.Errorf("ERROR %v", err)
		}
	}
	return nil
}

//query shared wallet balance without bidding result
func (c *AuctionContract) ReadSharedWallet(ctx contractapi.TransactionContextInterface, address string) (*SharedWallet, error) {
	addressSW := Hash(address)
	bytes, _ := ctx.GetStub().GetState(addressSW)

	var sharedWallet SharedWallet
	json.Unmarshal(bytes, &sharedWallet)

	return &sharedWallet, nil
}

//store user's smart meter data
func (c *AuctionContract) StoreSM(ctx contractapi.TransactionContextInterface, username string, t string, amount string) error {
	//query user's smArray
	userSmArray, err := c.QuerySM(ctx, username)
	if err != nil {
		return err
	}
	//calls StoreSmData
	StoreSmData(t, amount, userSmArray)
	newBytes, _ := json.Marshal(userSmArray)
	smAddress := Hash(username + "1")
	return ctx.GetStub().PutState(smAddress, newBytes)
}

//query user's smart meter by username
func (c *AuctionContract) QuerySM(ctx contractapi.TransactionContextInterface, username string) (*SMarray, error) {
	username_new := username + "1"
	address_sm := Hash(username_new)
	bytes, _ := ctx.GetStub().GetState(address_sm)
	var smArray SMarray
	json.Unmarshal(bytes, &smArray)
	return &smArray, nil
}

// read account information by name
func (c *AuctionContract) ReadAccounts(ctx contractapi.TransactionContextInterface, addr string) (*Accounts1, error) {

	address := Hash(addr)

	bytes, err := ctx.GetStub().GetState(address)
	if err != nil {
		return nil, fmt.Errorf("failed to read from world state: %v", err)
	}
	if bytes == nil {
		return nil, fmt.Errorf("the asset %s does not exist", addr)
	}

	var accounts1 Accounts1
	err = json.Unmarshal(bytes, &accounts1)
	if err != nil {
		return nil, err
	}
	return &accounts1, nil
}

// read account information by address
func (c *AuctionContract) ReadAccounts2(ctx contractapi.TransactionContextInterface, address string) (*Accounts1, error) {

	bytes, err := ctx.GetStub().GetState(address)
	if err != nil {
		return nil, fmt.Errorf("failed to read from world state: %v", err)
	}
	if bytes == nil {
		return nil, fmt.Errorf("the asset %s does not exist", address)
	}
	var accounts1 Accounts1
	err = json.Unmarshal(bytes, &accounts1)
	if err != nil {
		return nil, err
	}
	return &accounts1, nil
}

func (c *AuctionContract) GetAllAssets(ctx contractapi.TransactionContextInterface) ([]*Accounts1, error) {
	// range query with empty string for startKey and endKey does an
	// open-ended query of all assets in the chaincode namespace.
	resultsIterator, err := ctx.GetStub().GetStateByRange("", "")
	if err != nil {
		return nil, err
	}
	defer resultsIterator.Close()

	var accounts1s []*Accounts1
	for resultsIterator.HasNext() {
		queryResponse, err := resultsIterator.Next()
		if err != nil {
			return nil, err
		}

		var accounts1 Accounts1
		err = json.Unmarshal(queryResponse.Value, &accounts1)
		if err != nil {
			return nil, err
		}
		accounts1s = append(accounts1s, &accounts1)
	}

	return accounts1s, nil
}

// CreateAuction creates a new instance of Auction
func (c *AuctionContract) CreateAuction(ctx contractapi.TransactionContextInterface, auctionID string) error {
	exists, err := c.AuctionExists(ctx, auctionID)
	if err != nil {
		return fmt.Errorf("could not read from world state. %s", err)
	} else if exists {
		return fmt.Errorf("the auction %s already exists", auctionID)
	}

	auction := new(Auction)
	auction.Closed = false
	bytes, _ := json.Marshal(auction)
	return ctx.GetStub().PutState(auctionID, bytes)
}

// QueryAuction retrieves an instance of Auction from the world state
func (c *AuctionContract) QueryAuction(ctx contractapi.TransactionContextInterface, auctionID string) (string, error) {
	exists, err := c.AuctionExists(ctx, auctionID)
	if err != nil {
		return "", fmt.Errorf("could not read from world state. %s", err)
	} else if !exists {
		return "", fmt.Errorf("the auction %s does not exist", auctionID)
	}

	bytes, _ := ctx.GetStub().GetState(auctionID)
	auction := new(Auction)
	err = json.Unmarshal(bytes, auction)

	if err != nil {
		return "", fmt.Errorf("could not unmarshal world state data to type Auction")
	}

	return string(bytes), nil
}

// QueryAuction retrieves an instance of Auction from the world state
func (c *AuctionContract) QueryAccounts(ctx contractapi.TransactionContextInterface) (string, error) {
	var logger = flogging.MustGetLogger("fabric-double-auction")
	bytes, _ := ctx.GetStub().GetState("acc")
	accounts := new(Accounts)
	err := json.Unmarshal(bytes, accounts)
	if err != nil {
		return "", fmt.Errorf("could not unmarshal world state data to type Auction")
	}
	arrayLength := len(accounts.Address)
	logger.Error("arrayLength: ", arrayLength)
	return string(arrayLength), nil
}

// DeleteAuction deletes an instance of Auction from the world state
func (c *AuctionContract) CloseAuction(ctx contractapi.TransactionContextInterface, auctionID string) error {
	exists, err := c.AuctionExists(ctx, auctionID)
	if err != nil {
		return fmt.Errorf("could not read from world state. %s", err)
	} else if !exists {
		return fmt.Errorf("the auction %s does not exist", auctionID)
	}

	return ctx.GetStub().DelState(auctionID)
}

func (c *AuctionContract) Bid(ctx contractapi.TransactionContextInterface, auctionID string, prices string, quantities string, addr string) error {
	bytes, _ := ctx.GetStub().GetState("acc")
	accounts := new(Accounts)
	err := json.Unmarshal(bytes, accounts)
	if err != nil {
		return fmt.Errorf("could not unmarshal world state data to type Auction")
	}

	exists, err := c.AuctionExists(ctx, auctionID)
	if err != nil {
		return fmt.Errorf("could not read from world state. %s", err)
	} else if !exists {
		return fmt.Errorf("no %s auction", auctionID)
	}

	bytes, _ = ctx.GetStub().GetState(auctionID)
	auction := new(Auction)
	json.Unmarshal(bytes, auction)
	found := false
	// The element to search for
	element := Hash(addr)
	// Iterate over the elements of the list, it can be finished in a simpler way
	for _, e := range accounts.Address {
		if e == element {
			found = true
			break
		}
	}
	if found == true {
		AddBid(Hash(addr), StrToFloatArr(prices), StrToIntArr(quantities), auction)
		newBytes, _ := json.Marshal(auction)
		return ctx.GetStub().PutState(auctionID, newBytes)
	} else {
		return fmt.Errorf("Account cannot found in the system")
	}
}

// Claer all bids
//func (c *AuctionContract) ClearBids(ctx contractapi.TransactionContextInterface, auctionID string) error {
//	exists, err := c.AuctionExists(ctx, auctionID)
//	if err != nil {
//		return fmt.Errorf("could not read from world state. %s", err)
//	} else if !exists {
//		return fmt.Errorf("no %s auction", auctionID)
//	}
//
//	err = ctx.GetStub().DelState(auctionID)
//	return err
//}

// Claer all bids
func (c *AuctionContract) ClearBids(ctx contractapi.TransactionContextInterface, auctionID string) error {
	exists, err := c.AuctionExists(ctx, auctionID)
	if err != nil {
		return fmt.Errorf("could not read from world state. %s", err)
	} else if !exists {
		return fmt.Errorf("no %s auction", auctionID)
	}
	bytes, _ := ctx.GetStub().GetState(auctionID)
	auction := new(Auction)
	json.Unmarshal(bytes, auction)
	auction.Buyers = []BuyerBid{}
	auction.Sellers = []SellerBid{}
	auction.BuyersPay = [20]float64{}
	auction.SellersPay = [20]float64{}
	bytes, _ = json.Marshal(auction)
	ctx.GetStub().PutState(auctionID, bytes)
	return err
}

func (c *AuctionContract) Withdraw(ctx contractapi.TransactionContextInterface, auctionID string, addr string) error {
	var logger = flogging.MustGetLogger("fabric-double-auction")

	exists, err := c.AuctionExists(ctx, auctionID)
	if err != nil {
		return fmt.Errorf("could not read from world state. %s", err)
	} else if !exists {
		return fmt.Errorf("no %s auction", auctionID)
	}

	bytes, _ := ctx.GetStub().GetState(auctionID)
	auction := new(Auction)
	json.Unmarshal(bytes, auction)
	if !auction.Closed {
		// winners := Allocate(auction.Buyers, auction.Sellers)

		bytes, _ = ctx.GetStub().GetState("acc")
		accounts := new(Accounts)
		err = json.Unmarshal(bytes, accounts)
		if err != nil {
			return fmt.Errorf("could not unmarshal world state data to type Auction")
		}
		logger.Error("-----------------------------------------")
		logger.Error("Buyer", auction.Buyers)
		logger.Error("-----------------------------------------")
		logger.Error("-----------------------------------------")
		logger.Error("Seller", auction.Sellers)
		logger.Error("-----------------------------------------")

		for i := 0; i < len(auction.Sellers); i++ {
			saddr := auction.Sellers[i].Address

			for j := 0; j < len(accounts.Address); j++ {
				if saddr == accounts.Address[j] {
					c.Refund(ctx, saddr, "001", auction.SellersPay[i], 3)
					c.Refund(ctx, saddr, "001", auction.SellersPay[i], 4)
					break
				}
			}
		}
		bytes, _ = json.Marshal(accounts)
		ctx.GetStub().PutState("acc", bytes)
	}

	return nil
}

func (c *AuctionContract) HtlcExists(ctx contractapi.TransactionContextInterface, id string) (bool, error) {
	htlcJSON, err := ctx.GetStub().GetState(id)
	if err != nil {
		return false, fmt.Errorf("failed to read from world state: %v", err)
	}
	return htlcJSON != nil, nil
}

//create htlc
func (c *AuctionContract) CreateHash(ctx contractapi.TransactionContextInterface, id string, amount float64, premage int, addr string) error {
	//clientMSPID, err := ctx.GetClientIdentity().GetMSPID()
	exists, err := c.HtlcExists(ctx, id)
	if err != nil {
		return err
	}
	if exists {
		return fmt.Errorf("the asset %s already exists", id)
	}
	if err != nil {
		return fmt.Errorf("failed to get MSPID: %v", err)
	}

	if err != nil {
		return fmt.Errorf("failed to get senderclient id: %v", err)
	}

	if amount <= 0 {
		return fmt.Errorf("sender amount must be a positive integer")
	}

	address := Hash(addr)
	account, err := c.ReadAccounts2(ctx, address)
	if err != nil {
		return fmt.Errorf("failed to get readaccount : %v", err)
	}

	hashByte := sha256.Sum256([]byte(strconv.Itoa(premage)))

	hashCode := hex.EncodeToString(hashByte[:])
	state := 0

	htlc := Htlc{
		Id:     id,
		Sender: account.Address,
		Amount: amount,

		HashValue: hashCode,
		State:     state,
	}

	htlcByte, err := json.Marshal(htlc)
	if err != nil {
		return err
	}

	return ctx.GetStub().PutState(id, htlcByte)
}

func (c *AuctionContract) QueryTransId(ctx contractapi.TransactionContextInterface, id string) (*Htlc, error) {
	htlcJSON, err := ctx.GetStub().GetState(id)
	if err != nil {
		return nil, fmt.Errorf("failed to read from world state: %v", err)
	}
	if htlcJSON == nil {
		return nil, fmt.Errorf("the htlc %s does not exist", id)
	}

	var htlc Htlc
	err = json.Unmarshal(htlcJSON, &htlc)
	if err != nil {
		return nil, err
	}

	return &htlc, nil
}

//transfer token
func (c *AuctionContract) transfer(ctx contractapi.TransactionContextInterface, from string, to string, value float64) error {

	if from == to {
		return fmt.Errorf("cannot transfer to and from same client account")
	}

	if value < 0 { // transfer of 0 is allowed in ERC-20, so just validate against negative amounts
		return fmt.Errorf("transfer amount cannot be negative")
	}

	//get sender assets
	senderAsset, err := c.ReadAccounts2(ctx, from)
	if err != nil {
		return fmt.Errorf("failed to get account %v", err)
	}

	//get reveive assets
	receiveAsset, err := c.ReadAccounts2(ctx, to)
	if err != nil {
		return fmt.Errorf("failed to read receive asset %s from world state: %v", to, err)
	}

	//transaction
	senderAsset.Balance -= value
	receiveAsset.Balance += value

	//update
	assetJSON, err := json.Marshal(senderAsset)
	if err != nil {
		return err
	}
	err = ctx.GetStub().PutState(from, assetJSON)
	if err != nil {
		return nil
	}

	assetJSON2, err := json.Marshal(receiveAsset)
	if err != nil {
		return err
	}
	err = ctx.GetStub().PutState(to, assetJSON2)
	if err != nil {
		return nil
	}
	return nil
}

//exchange assets
func (c *AuctionContract) AcrossTransfer(ctx contractapi.TransactionContextInterface, pwd int, id string, addr string) error {
	//get bao(buy) address

	asset1, err := c.ReadAccounts(ctx, addr)
	if err != nil {
		return fmt.Errorf("failed to get account : %v", err)
	}

	receipt, err := ctx.GetClientIdentity().GetID()
	if err != nil {
		return fmt.Errorf("failed to get receipetclient id: %v", err)
	}
	//call function
	//var htlc Htlc
	htlc, err := c.QueryTransId(ctx, id)
	if err != nil {
		return err
	}

	pwdByte := sha256.Sum256([]byte(strconv.Itoa(pwd)))
	hashCode := hex.EncodeToString(pwdByte[:])
	if hashCode != htlc.HashValue {
		return fmt.Errorf("the hash does not match!") //if you change code when the produce is running, you must invoke it again!
	}
	// Verify if double spend
	if htlc.State != 0 {
		return fmt.Errorf("this htlc transaction state is error")
	}

	err = c.transfer(ctx, htlc.Sender, asset1.Address, htlc.Amount)
	if err != nil {
		return fmt.Errorf("failed to transfer: %v", err)
	}
	//wirte state
	htlc.State = 1
	htlcByte, err := json.Marshal(htlc)
	if err != nil {
		return err
	}
	ctx.GetStub().PutState(id, htlcByte)

	// Emit the Transfer event
	transferEvent := event{htlc.Sender, receipt, htlc.Amount}
	transferEventJSON, err := json.Marshal(transferEvent)
	if err != nil {
		return fmt.Errorf("failed to obtain JSON encoding: %v", err)
	}
	err = ctx.GetStub().SetEvent("Transfer", transferEventJSON)
	if err != nil {
		return fmt.Errorf("failed to set event: %v", err)
	}

	return nil
}
