	SELECT
		 TTC.DatabaseName
		,TTC.SchemaName
		,TTC.TableName
	INTO {{DB_NAME}}.dbo.MissingTables
	FROM
		{{DB_NAME}}.dbo.TablesToConvert TTC
			LEFT JOIN {{DB_NAME}}.dbo.TableUsedSelects SEL ON TTC.DatabaseName=SEL.DatabaseName AND TTC.SchemaName=SEL.SchemaName AND TTC.TableName=SEL.TableName
	WHERE
		SEL.TableName IS NULL
	ORDER BY 
		TTC.DatabaseName,TTC.SchemaName,TTC.TableName
GO
	SELECT COUNT(*) FROM {{DB_NAME}}.dbo.MissingTables
GO