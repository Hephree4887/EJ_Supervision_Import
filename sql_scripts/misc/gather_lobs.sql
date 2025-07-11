	DROP TABLE IF EXISTS {{DB_NAME}}.dbo.LOB_COLUMN_UPDATES
GO
CREATE TABLE {{DB_NAME}}.dbo.LOB_COLUMN_UPDATES 
	(
		SchemaName VARCHAR(128) NOT NULL,TableName VARCHAR(128) NOT NULL,ColumnName VARCHAR(128) NOT NULL,DataType VARCHAR(128) NOT NULL,
		CurrentLength INT NULL,MaxLen INT NULL,RowCnt INT NULL,AlterStatement VARCHAR(MAX) NULL,ProcessDate DATETIME NOT NULL DEFAULT GETDATE(),
		PRIMARY KEY (SchemaName, TableName, ColumnName)
	)
GO