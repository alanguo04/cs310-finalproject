USE photoapp;

DROP TABLE IF EXISTS runs;
DROP TABLE IF EXISTS runsegments;

CREATE TABLE runs
(
	runid int not null AUTO_INCREMENT,
	visualizationlink varchar(128),
    PRIMARY KEY (runid)
);

ALTER TABLE runs AUTO_INCREMENT = 1001;

CREATE TABLE runsegments
(
	runid          int not null REFERENCES runs(runid),
    lat             DECIMAL(9,6)  NOT NULL,
    lon             DECIMAL(9,6)  NOT NULL,
    time            TIMESTAMP     NOT NULL,
    elevation       DECIMAL(8,2),
    temperature     DECIMAL(5,2),
    humidity        DECIMAL(5,2),
--     wind_speed      DECIMAL(5,2),
--     wind_direction  DECIMAL(5,2),
	precipitation   DECIMAL(5,2),
    pace            DECIMAL(6,2),
    adjusted_pace   DECIMAL(6,2)
);