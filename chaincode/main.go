package main

import (
	"encoding/json"
	"fmt"
	"log"

	"github.com/hyperledger/fabric-contract-api-go/contractapi"
)

// SmartContract provides functions for managing an IoT Record
type SmartContract struct {
	contractapi.Contract
}

// IoTRecord describes basic details of what makes up an IoT Record
type IoTRecord struct {
	ReadingID   string `json:"reading_id"`
	DeviceID    string `json:"device_id"`
	PayloadHash string `json:"payload_hash"`
	Timestamp   string `json:"timestamp"`
}

// CreateRecord adds a new record to the world state with given details
func (s *SmartContract) CreateRecord(ctx contractapi.TransactionContextInterface, readingID string, deviceID string, payloadHash string, timestamp string) error {
	exists, err := s.RecordExists(ctx, readingID)
	if err != nil {
		return err
	}
	if exists {
		return fmt.Errorf("the record %s already exists", readingID)
	}

	record := IoTRecord{
		ReadingID:   readingID,
		DeviceID:    deviceID,
		PayloadHash: payloadHash,
		Timestamp:   timestamp,
	}

	recordJSON, err := json.Marshal(record)
	if err != nil {
		return err
	}

	return ctx.GetStub().PutState(readingID, recordJSON)
}

// ReadRecord returns the record stored in the world state with given id
func (s *SmartContract) ReadRecord(ctx contractapi.TransactionContextInterface, readingID string) (*IoTRecord, error) {
	recordJSON, err := ctx.GetStub().GetState(readingID)
	if err != nil {
		return nil, fmt.Errorf("failed to read from world state: %v", err)
	}
	if recordJSON == nil {
		return nil, fmt.Errorf("the record %s does not exist", readingID)
	}

	var record IoTRecord
	err = json.Unmarshal(recordJSON, &record)
	if err != nil {
		return nil, err
	}

	return &record, nil
}

// RecordExists returns true when record with given ID exists in world state
func (s *SmartContract) RecordExists(ctx contractapi.TransactionContextInterface, readingID string) (bool, error) {
	recordJSON, err := ctx.GetStub().GetState(readingID)
	if err != nil {
		return false, fmt.Errorf("failed to read from world state: %v", err)
	}

	return recordJSON != nil, nil
}

func main() {
	iotChaincode, err := contractapi.NewChaincode(&SmartContract{})
	if err != nil {
		log.Panicf("Error creating IoT chaincode: %v", err)
	}

	if err := iotChaincode.Start(); err != nil {
		log.Panicf("Error starting IoT chaincode: %v", err)
	}
}
